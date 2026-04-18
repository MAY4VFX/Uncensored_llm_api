from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any

import httpx

from app.config import settings
from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest


class ModalProviderError(RuntimeError):
    pass


def supports_runtime(profile: dict[str, Any]) -> bool:
    return profile.get("family") != "gguf"


def _provider_config(model: LlmModel) -> dict[str, Any]:
    return dict(model.provider_config or {})


def _modal_gpu_value(value: str | None) -> str:
    gpu = (value or "").strip()
    mapping = {
        "RTX_4000_Ada_20GB": "A10G",
        "RTX_A5000_24GB": "A10G",
        "A100_80GB": "A100-80GB",
        "H100_80GB": "H100",
        "H200_141GB": "H200",
        "H200_143GB": "H200",
    }
    return mapping.get(gpu, gpu or "H100")


def _modal_env(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, str]:
    config = _provider_config(model)
    app_name = config.get("app_name") or f"{settings.modal_app_prefix}-{model.slug}"
    function_name = config.get("function_name") or "openai_api"
    volume_name = config.get("volume_name") or f"{app_name}-weights"
    runtime_image = config.get("image") or default_image or ""

    env = {
        "MODAL_APP_NAME": app_name,
        "MODAL_FUNCTION_NAME": function_name,
        "MODAL_MODEL_NAME": model.hf_repo,
        "MODAL_MAX_MODEL_LEN": str(profile.get("target_context") or model.max_context_length or 4096),
        "MODAL_GPU": _modal_gpu_value(str(profile.get("gpu_type") or model.gpu_type or config.get("gpu"))),
        "MODAL_TIMEOUT_SECONDS": str(config.get("timeout_seconds") or 3600),
        "MODAL_STARTUP_TIMEOUT_SECONDS": str(config.get("startup_timeout_seconds") or profile.get("runpod_init_timeout") or 1800),
        "MODAL_SCALEDOWN_WINDOW_SECONDS": str(config.get("scaledown_window_seconds") or 600),
        "MODAL_MIN_CONTAINERS": str(config.get("min_containers") or 0),
        "MODAL_MAX_CONTAINERS": str(config.get("max_containers") or max(1, model.gpu_count or 1)),
        "MODAL_BUFFER_CONTAINERS": str(config.get("buffer_containers") or 0),
        "MODAL_VOLUME_NAME": volume_name,
        "MODAL_RUNTIME_IMAGE": str(runtime_image),
        "MODAL_RUNTIME_ARGS_JSON": json.dumps(profile.get("runtime_args") or {}),
        "MODAL_TOOL_PARSER": str(profile.get("tool_parser") or "none"),
        "MODAL_GENERATION_CONFIG_MODE": str(profile.get("generation_config_mode") or "vllm"),
        "MODAL_ENVIRONMENT": settings.modal_environment,
        "MODAL_APP_PREFIX": settings.modal_app_prefix,
    }
    if profile.get("reasoning_parser"):
        env["MODAL_REASONING_PARSER"] = str(profile["reasoning_parser"])
    if profile.get("default_temperature") is not None:
        env["MODAL_DEFAULT_TEMPERATURE"] = str(profile["default_temperature"])
    if profile.get("gpu_memory_utilization") is not None:
        env["MODAL_GPU_MEMORY_UTILIZATION"] = str(profile["gpu_memory_utilization"])
    if profile.get("enforce_eager"):
        env["MODAL_ENFORCE_EAGER"] = "true"
    if settings.hf_token:
        env["HF_TOKEN"] = settings.hf_token
    env.update(settings.modal_secrets_env)
    return env


def _run_modal_runtime_blocking(env: dict[str, str]) -> dict[str, Any]:
    if not settings.modal_enabled:
        raise ModalProviderError("Modal credentials are not configured")
    runtime_path = os.path.join(os.path.dirname(__file__), "modal_runtime.py")
    proc = subprocess.run(
        ["python", runtime_path, "deploy"],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
    )
    if proc.returncode != 0:
        raise ModalProviderError(proc.stderr.strip() or proc.stdout.strip() or "Modal runtime deploy failed")
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ModalProviderError(f"Modal runtime returned invalid JSON: {proc.stdout.strip()}") from exc


async def _run_modal_runtime(env: dict[str, str]) -> dict[str, Any]:
    return await asyncio.to_thread(_run_modal_runtime_blocking, env)


async def deploy_model(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, Any]:
    env = _modal_env(model, profile, default_image=default_image)
    result = await _run_modal_runtime(env)
    deployment_ref = result.get("app_id") or result.get("app_name")
    provider_config = {
        **_provider_config(model),
        "app_name": result.get("app_name"),
        "app_id": result.get("app_id"),
        "function_name": result.get("function_name"),
        "web_url": result.get("web_url"),
        "environment": result.get("environment"),
        "volume_name": result.get("volume_name"),
        "gpu": result.get("gpu"),
        "image": env.get("MODAL_RUNTIME_IMAGE"),
    }
    return {
        "deployment_ref": deployment_ref,
        "provider_status": "active",
        "provider_config": provider_config,
        "web_url": result.get("web_url"),
    }


async def redeploy_model(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, Any]:
    return await deploy_model(model, profile, default_image=default_image)


def _update_min_containers_blocking(app_name: str, function_name: str, env_name: str, count: int) -> None:
    proc = subprocess.run(
        ["python", "-c",
         "import sys, modal; "
         "fn = modal.Function.from_name(sys.argv[1], sys.argv[2], environment_name=sys.argv[3]); "
         "fn.update_autoscaler(min_containers=int(sys.argv[4]))",
         app_name, function_name, env_name, str(count)],
        capture_output=True, text=True,
        env={**os.environ, **settings.modal_secrets_env},
        check=False,
    )
    if proc.returncode != 0:
        raise ModalProviderError(proc.stderr.strip() or proc.stdout.strip() or "update_autoscaler failed")


async def update_min_containers(model: LlmModel, count: int) -> bool:
    if not settings.modal_enabled:
        raise ModalProviderError("Modal credentials are not configured")
    config = _provider_config(model)
    app_name = config.get("app_name") or f"{settings.modal_app_prefix}-{model.slug}"
    function_name = config.get("function_name") or "openai_api"
    env_name = config.get("environment") or settings.modal_environment
    await asyncio.to_thread(_update_min_containers_blocking, app_name, function_name, env_name, count)
    return True


async def disable_model(model: LlmModel) -> dict[str, Any]:
    config = _provider_config(model)
    provider_config = {**config, "disabled": True}
    return {
        "deployment_ref": model.deployment_ref,
        "provider_status": "inactive",
        "provider_config": provider_config,
    }


_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_TTL = 15.0


async def get_status(model: LlmModel) -> dict[str, Any]:
    import time
    config = _provider_config(model)
    web_url = config.get("web_url")
    if not web_url:
        return {
            "status": model.provider_status or "inactive",
            "estimated_wait_seconds": 0,
            "workers_ready": 0,
            "throttled": 0,
            "message": "Modal deployment URL is not configured",
        }
    cached = _STATUS_CACHE.get(web_url)
    if cached and time.time() - cached[0] < _STATUS_TTL:
        return cached[1]

    health_url = web_url.rstrip("/") + "/health"
    result: dict[str, Any]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=8.0, write=8.0, pool=None)) as client:
            response = await client.get(health_url)
            if response.status_code == 200:
                result = {
                    "status": "ready",
                    "estimated_wait_seconds": 0,
                    "workers_ready": 1,
                    "throttled": 0,
                    "message": "Modal container ready",
                }
                _STATUS_CACHE[web_url] = (time.time(), result)
                return result
    except Exception:
        pass
    eta = 240 if (model.params_b or 0) >= 100 else 90
    result = {
        "status": "warming_up",
        "estimated_wait_seconds": eta,
        "workers_ready": 0,
        "throttled": 0,
        "message": f"Modal cold-start (~{eta // 60} min)",
    }
    _STATUS_CACHE[web_url] = (time.time(), result)
    return result


def _modal_web_url(model: LlmModel) -> str:
    config = _provider_config(model)
    web_url = config.get("web_url")
    if not web_url:
        raise ModalProviderError("Modal deployment URL is not configured")
    return str(web_url).rstrip("/")


def _patch_gpt_oss_stops(payload: dict, model: LlmModel) -> None:
    # Same workaround as proxy_service for RunPod path: gpt-oss harmony
    # parser crashes with HarmonyError when model emits 200012 (<|call|>)
    # without 199999 (<|return|>) in the EOS list. Inject both stop tokens
    # so vLLM ends generation at the OpenAI-intended point.
    repo = (model.hf_repo or "").lower()
    if "gpt-oss" not in repo and "gpt_oss" not in repo:
        return
    existing = payload.get("stop_token_ids") or []
    for tid in (199999, 200012):
        if tid not in existing:
            existing.append(tid)
    payload["stop_token_ids"] = existing


async def run_chat(request: ChatCompletionRequest, model: LlmModel) -> dict[str, Any]:
    # vLLM 0.19.1 with openai_gptoss reasoning parser crashes in
    # chat_completion_full_generator (HarmonyError on bad first tokens).
    # Always stream from vLLM and accumulate locally to bypass the
    # non-stream harmony path. Returned shape stays OpenAI-compat.
    payload = {
        "model": model.hf_repo,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens or 4096,
        "top_p": request.top_p,
        "stream": True,
    }
    if request.tools:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = request.response_format
    _patch_gpt_oss_stops(payload, model)

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_acc: dict[int, dict] = {}
    finish_reason = "stop"
    response_id = ""
    created = 0
    served_model = model.hf_repo
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    last_exc: Exception | None = None
    for attempt in range(3):
        chunks_received = 0
        content_parts.clear() if content_parts else None
        reasoning_parts.clear() if reasoning_parts else None
        tool_calls_acc.clear()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=None)) as client:
                async with client.stream("POST", _modal_web_url(model) + "/v1/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    buf = ""
                    async for chunk in response.aiter_text():
                        chunks_received += 1
                        buf += chunk
                        while "\n\n" in buf:
                            frame, buf = buf.split("\n\n", 1)
                            for line in frame.split("\n"):
                                if not line.startswith("data: "):
                                    continue
                                data = line[6:].strip()
                                if data == "[DONE]":
                                    continue
                                try:
                                    obj = json.loads(data)
                                except Exception:
                                    continue
                                response_id = obj.get("id") or response_id
                                created = obj.get("created") or created
                                served_model = obj.get("model") or served_model
                                if obj.get("usage"):
                                    usage = obj["usage"]
                                for ch in obj.get("choices", []) or []:
                                    delta = ch.get("delta", {}) or {}
                                    if delta.get("content"):
                                        content_parts.append(delta["content"])
                                    if delta.get("reasoning"):
                                        reasoning_parts.append(delta["reasoning"])
                                    for tc in delta.get("tool_calls") or []:
                                        idx = tc.get("index", 0)
                                        slot = tool_calls_acc.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                                        if tc.get("id"):
                                            slot["id"] = tc["id"]
                                        if tc.get("type"):
                                            slot["type"] = tc["type"]
                                        fn = tc.get("function") or {}
                                        if fn.get("name"):
                                            slot["function"]["name"] += fn["name"]
                                        if fn.get("arguments") is not None:
                                            slot["function"]["arguments"] += fn["arguments"]
                                    if ch.get("finish_reason"):
                                        finish_reason = ch["finish_reason"]
            if chunks_received == 0:
                last_exc = RuntimeError("Modal returned empty stream")
                await asyncio.sleep(2 + attempt * 3)
                continue
            last_exc = None
            break
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            await asyncio.sleep(2 + attempt * 3)
            continue
    if last_exc is not None and not (content_parts or reasoning_parts or tool_calls_acc):
        raise ModalProviderError(f"Modal failed after retries: {type(last_exc).__name__}: {last_exc}")

    message = {"role": "assistant", "content": "".join(content_parts) or None}
    if reasoning_parts:
        message["reasoning"] = "".join(reasoning_parts)
    if tool_calls_acc:
        message["tool_calls"] = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        message["content"] = None
    return {
        "id": response_id or "chatcmpl-modal",
        "object": "chat.completion",
        "created": created,
        "model": served_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


async def stream_chat(request: ChatCompletionRequest, model: LlmModel):
    import asyncio
    payload = {
        "model": model.hf_repo,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens or 4096,
        "top_p": request.top_p,
        "stream": True,
    }
    if request.tools:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = request.response_format
    _patch_gpt_oss_stops(payload, model)

    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=128)

    async def _producer():
        last_exc = None
        for attempt in range(3):
            chunks_received = 0
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=None)) as client:
                    async with client.stream("POST", _modal_web_url(model) + "/v1/chat/completions", json=payload) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_text():
                            if chunk:
                                chunks_received += 1
                                await queue.put(chunk)
                if chunks_received == 0:
                    last_exc = RuntimeError("Modal returned empty stream")
                    await asyncio.sleep(2 + attempt * 3)
                    continue
                last_exc = None
                break
            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                await asyncio.sleep(2 + attempt * 3)
                continue
            except Exception as exc:
                last_exc = exc
                break
        if last_exc is not None:
            await queue.put(f"data: {{\"error\":\"{type(last_exc).__name__}: {str(last_exc)[:200]}\"}}\n\n")
        await queue.put(None)

    task = asyncio.create_task(_producer())
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if chunk is None:
                break
            yield chunk
    finally:
        if not task.done():
            task.cancel()
