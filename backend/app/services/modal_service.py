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


async def get_status(model: LlmModel) -> dict[str, Any]:
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
    health_url = web_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(health_url)
            if response.status_code == 200:
                return {
                    "status": "ready",
                    "estimated_wait_seconds": 0,
                    "workers_ready": 1,
                    "throttled": 0,
                    "message": "Modal container ready",
                }
    except Exception:
        pass
    eta = 240 if (model.params_b or 0) >= 100 else 90
    return {
        "status": "warming_up",
        "estimated_wait_seconds": eta,
        "workers_ready": 0,
        "throttled": 0,
        "message": f"Modal cold-start (~{eta // 60} min)",
    }


def _modal_web_url(model: LlmModel) -> str:
    config = _provider_config(model)
    web_url = config.get("web_url")
    if not web_url:
        raise ModalProviderError("Modal deployment URL is not configured")
    return str(web_url).rstrip("/")


async def run_chat(request: ChatCompletionRequest, model: LlmModel) -> dict[str, Any]:
    payload = {
        "model": model.hf_repo,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens or 4096,
        "top_p": request.top_p,
        "stream": False,
    }
    if request.tools:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = request.response_format
    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(_modal_web_url(model) + "/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()


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

    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=128)

    async def _producer():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=None)) as client:
                async with client.stream("POST", _modal_web_url(model) + "/v1/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_text():
                        if chunk:
                            await queue.put(chunk)
        except Exception as exc:
            await queue.put(f"data: {{\"error\":\"{type(exc).__name__}: {str(exc)[:200]}\"}}\n\n")
        finally:
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
