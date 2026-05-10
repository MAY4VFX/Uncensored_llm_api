from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from typing import Any

import httpx

from app.config import settings
from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest
from app.services.runpod_service import _resolve_gguf


class ModalProviderError(RuntimeError):
    pass


# Shared long-lived httpx client. Per-request AsyncClient делал новый TLS handshake +
# DNS resolve, что под параллельной нагрузкой к Modal приводило к ConnectTimeout
# на отдельных запросах (httpx без happy-eyeballs залипал на одном из 4+ A-records).
# Single pooled client реюзает keep-alive TCP, DNS/connect делается один раз.
_shared_client: httpx.AsyncClient | None = None
_shared_client_lock = asyncio.Lock()


async def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _shared_client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(connect=60.0, read=None, write=30.0, pool=10.0),
                    limits=httpx.Limits(
                        max_connections=200,
                        max_keepalive_connections=50,
                        keepalive_expiry=30.0,
                    ),
                    follow_redirects=True,
                )
    return _shared_client


async def aclose_shared_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


def supports_runtime(profile: dict[str, Any]) -> bool:
    family = str(profile.get("family") or "").strip()
    return bool(family)


def _provider_config(model: LlmModel) -> dict[str, Any]:
    return dict(model.provider_config or {})


def _sanitize_modal_part(value: str, fallback: str, max_len: int = 63) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    if not cleaned:
        cleaned = fallback
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    return cleaned[: max_len - 9].rstrip("-") + "-" + digest


def _default_modal_app_name(model: LlmModel) -> str:
    prefix = _sanitize_modal_part(settings.modal_app_prefix, "unchained")
    slug = _sanitize_modal_part(model.slug or model.hf_repo or "model", "model")
    return _sanitize_modal_part(f"{prefix}-{slug}", "unchained-model", max_len=63)


def _default_modal_volume_name(app_name: str) -> str:
    return _sanitize_modal_part(f"{app_name}-weights", "modal-weights", max_len=63)


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


async def _modal_env(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, str]:
    config = _provider_config(model)
    family = str(profile.get("family") or "").strip().lower()
    app_name = config.get("app_name") or _default_modal_app_name(model)
    function_name = config.get("function_name") or "openai_api"
    volume_name = config.get("volume_name") or _default_modal_volume_name(app_name)
    runtime_image = (
        profile.get("modal_docker_image")
        or config.get("image")
        or default_image
        or ""
    )
    runtime_args = dict(profile.get("runtime_args") or {})

    gguf_env: dict[str, str] = {}
    if family == "gguf":
        resolved = await _resolve_gguf(model.hf_repo)
        runtime_args.setdefault("gguf_file", resolved["gguf_file"])
        runtime_args.setdefault("ngl", 999)
        runtime_args.setdefault("parallel", 1)
        runtime_args.setdefault("jinja", True)
        runtime_args.setdefault("flash_attn", True)
        # Cache-reuse keeps partial prompt prefixes warm across diverging agent
        # branches; without it llama.cpp re-processes ~30k tokens per turn
        # whenever LCP similarity drops below the slot's threshold.
        runtime_args.setdefault("cache_reuse", 128)
        # Per Qwen3.6 model card and unsloth/buildmvpfast guidance for stable
        # agentic workflows: disable thinking via chat-template kwarg.
        # Qwen3.6 ships with thinking ON by default (no soft /no_think switch),
        # so this kwarg is the only way to turn it off.
        ctk = dict(runtime_args.get("chat_template_kwargs") or {})
        ctk.setdefault("enable_thinking", False)
        runtime_args["chat_template_kwargs"] = ctk
        runtime_image = str(config.get("image") or "ghcr.io/ggml-org/llama.cpp:server-cuda")
        gguf_env = {
            "MODAL_MODEL_FAMILY": "gguf",
            "MODAL_GGUF_RUNTIME": "llamacpp",
            "MODAL_GGUF_FILE": str(resolved["gguf_file"]),
            "MODAL_GGUF_BASE_MODEL": str(resolved.get("base_model") or ""),
            "MODAL_GGUF_HAS_CONFIG": "true" if resolved.get("has_config") else "false",
            "MODAL_LLAMA_SERVER_BINARY": str(config.get("llama_server_binary") or "/app/llama-server"),
            "MODAL_LOCAL_LLAMA_PORT": str(config.get("local_llama_port") or 8001),
        }

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
        "MODAL_RUNTIME_ARGS_JSON": json.dumps(runtime_args),
        "MODAL_TOOL_PARSER": str(profile.get("tool_parser") or "none"),
        "MODAL_GENERATION_CONFIG_MODE": str(profile.get("generation_config_mode") or "vllm"),
        "MODAL_ENVIRONMENT": settings.modal_environment,
        "MODAL_APP_PREFIX": settings.modal_app_prefix,
    }
    env.update(gguf_env)
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
    stdout = proc.stdout.strip()
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ModalProviderError(f"Modal runtime returned invalid JSON: {stdout}") from exc


async def _run_modal_runtime(env: dict[str, str]) -> dict[str, Any]:
    return await asyncio.to_thread(_run_modal_runtime_blocking, env)


async def deploy_model(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, Any]:
    env = await _modal_env(model, profile, default_image=default_image)
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
        # Read timeout must outlast vLLM's longest single-step latency. While
        # the engine is generating a heavy thinking response the event loop
        # can briefly delay /health by several seconds; an 8s ceiling falsely
        # flips the UI to "Warming up" on a hot container. 30s leaves room
        # for that and is still well under any realistic cold-start window.
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=30.0, write=8.0, pool=None)) as client:
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


def _serialize_messages(request: ChatCompletionRequest) -> list[dict[str, Any]]:
    """Preserve tool_calls / tool_call_id / name when forwarding messages."""
    out: list[dict[str, Any]] = []
    for m in request.messages:
        item: dict[str, Any] = {"role": m.role, "content": m.content}
        if getattr(m, "name", None):
            item["name"] = m.name
        if getattr(m, "tool_call_id", None):
            item["tool_call_id"] = m.tool_call_id
        if getattr(m, "tool_calls", None):
            item["tool_calls"] = m.tool_calls
        out.append(item)
    return out


def _tool_schema_by_name(tools: list[dict] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tool in tools or []:
        fn = tool.get("function") or {}
        name = fn.get("name")
        params = fn.get("parameters")
        if isinstance(name, str) and isinstance(params, dict):
            out[name] = params
    return out


def _schema_requires_empty_object(schema: dict[str, Any] | None) -> bool:
    if not isinstance(schema, dict):
        return False
    return (
        schema.get("type") == "object"
        and (schema.get("properties") or {}) == {}
        and (schema.get("required") or []) == []
        and schema.get("additionalProperties") is False
    )


def _is_empty_schema_websearch_helper(request: ChatCompletionRequest) -> bool:
    tools = request.tools or []
    if len(tools) != 1:
        return False
    fn = tools[0].get("function") or {}
    if fn.get("name") != "web_search":
        return False
    if not _schema_requires_empty_object(fn.get("parameters")):
        return False
    if len(request.messages) < 2:
        return False
    return request.messages[-1].content.startswith("Perform a web search for the query:")


def _is_webfetch_helper(request: ChatCompletionRequest) -> bool:
    tools = request.tools or []
    if len(tools) != 1:
        return False
    fn = tools[0].get("function") or {}
    if fn.get("name") != "WebFetch":
        return False
    params = fn.get("parameters") or {}
    props = params.get("properties") or {}
    fmt = props.get("format") or {}
    values = fmt.get("enum") or []
    if values != ["text", "markdown", "html"]:
        return False
    if len(request.messages) < 1:
        return False
    last = request.messages[-1].content.strip()
    return last.startswith("https://") or last.startswith("http://")


def _synthetic_web_search_stream() -> list[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    return [
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "web_search_helper", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "web_search_helper", "choices": [{"index": 0, "delta": {"reasoning": "We need to perform web search. Use function.", "reasoning_content": "We need to perform web search. Use function."}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "web_search_helper", "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "web_search_helper", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})}\n\n',
        'data: [DONE]\n\n',
    ]


def _synthetic_web_search_result() -> dict[str, Any]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": "web_search_helper",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "We need to perform web search. Use function.",
                "tool_calls": [{
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _synthetic_webfetch_stream(request: ChatCompletionRequest) -> list[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    url = request.messages[-1].content.strip()
    args = json.dumps({"url": url, "format": "text"})
    return [
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "webfetch_helper", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "webfetch_helper", "choices": [{"index": 0, "delta": {"reasoning": "We need to fetch this URL. Use function.", "reasoning_content": "We need to fetch this URL. Use function."}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "webfetch_helper", "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function", "function": {"name": "WebFetch", "arguments": args}}]}, "finish_reason": None}]})}\n\n',
        f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "webfetch_helper", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})}\n\n',
        'data: [DONE]\n\n',
    ]


def _synthetic_webfetch_result(request: ChatCompletionRequest) -> dict[str, Any]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    url = request.messages[-1].content.strip()
    args = json.dumps({"url": url, "format": "text"})
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": "webfetch_helper",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "We need to fetch this URL. Use function.",
                "tool_calls": [{
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": "WebFetch", "arguments": args},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def run_chat(request: ChatCompletionRequest, model: LlmModel) -> dict[str, Any]:
    if _is_empty_schema_websearch_helper(request):
        return _synthetic_web_search_result()
    if _is_webfetch_helper(request):
        return _synthetic_webfetch_result(request)

    # Always stream from vLLM and accumulate locally. Historically the
    # non-stream path through openai_gptoss crashed on v0.19.1 with
    # HarmonyError; we pinned back to v0.11.2 but stream-accumulate is
    # still the more defensive path for long cold starts.
    payload = {
        "model": model.hf_repo,
        "messages": _serialize_messages(request),
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
            client = await _get_shared_client()
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
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            await asyncio.sleep(2 + attempt * 3)
            continue
        except httpx.ConnectTimeout as exc:
            # Не ретраить: Modal LB уже принял попытку, ретрай только удваивает задержку.
            last_exc = exc
            break
    if last_exc is not None and not (content_parts or reasoning_parts or tool_calls_acc):
        raise ModalProviderError(f"Modal failed after retries: {type(last_exc).__name__}: {last_exc}")

    message = {"role": "assistant", "content": "".join(content_parts) or None}
    if reasoning_parts:
        message["reasoning"] = "".join(reasoning_parts)
    if tool_calls_acc:
        message["tool_calls"] = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        message["content"] = None
        # vLLM gpt-oss streaming bug (vllm-project/vllm#24076): с tool_calls часто
        # приходит finish_reason="stop". opencode/клиент тогда считает turn
        # законченным и не делает следующую итерацию agent loop. Форсим tool_calls
        # когда tool_calls присутствуют — как делают OpenRouter и другие gateway.
        finish_reason = "tool_calls"
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
    if _is_empty_schema_websearch_helper(request):
        for chunk in _synthetic_web_search_stream():
            yield chunk
        return
    if _is_webfetch_helper(request):
        for chunk in _synthetic_webfetch_stream(request):
            yield chunk
        return

    payload = {
        "model": model.hf_repo,
        "messages": _serialize_messages(request),
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
                client = await _get_shared_client()
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
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                await asyncio.sleep(2 + attempt * 3)
                continue
            except httpx.ConnectTimeout as exc:
                last_exc = exc
                break
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
