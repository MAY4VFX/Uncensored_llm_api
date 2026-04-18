import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, verify_api_key
from app.middleware.rate_limiter import check_rate_limit
from app.models.api_key import ApiKey
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.openai import ChatCompletionRequest
from app.services import proxy_service, runpod_service
from app.services.credits_service import check_credits, deduct_credits
from app.services.provider_service import MODAL, RUNPOD, get_provider_capabilities, resolve_model_provider
from app.services.usage_service import calculate_gpu_cost, count_message_tokens, estimate_max_cost, log_usage

router = APIRouter(tags=["chat"])


def _require_provider_capability(provider: str, capability: str, detail: str) -> None:
    capabilities = get_provider_capabilities(provider)
    if not capabilities.get(capability):
        raise HTTPException(status_code=400, detail=detail)


@router.get("/v1/models/{model_slug}/status")
async def model_status(
    model_slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).where(LlmModel.slug == model_slug, LlmModel.status == "active"))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_slug}' not found or not active")

    provider = await resolve_model_provider(model, db)
    capabilities = get_provider_capabilities(provider)

    if provider == RUNPOD:
        if not model.runpod_endpoint_id:
            return {
                "provider": provider,
                "status": "unavailable",
                "estimated_wait_seconds": 0,
                "workers_ready": 0,
                "throttled": 0,
                "capabilities": capabilities,
                "message": "Endpoint not configured",
            }
        worker = await runpod_service.check_worker_status(model.runpod_endpoint_id)
        return {
            "provider": provider,
            "status": worker["status"],
            "estimated_wait_seconds": worker["estimated_wait"],
            "workers_ready": worker["workers_ready"],
            "throttled": worker.get("throttled", 0),
            "capabilities": capabilities,
            "message": None,
        }

    return {
        "provider": provider,
        "status": model.provider_status or "provisioning",
        "estimated_wait_seconds": 0,
        "workers_ready": 0,
        "throttled": 0,
        "capabilities": capabilities,
        "message": "Modal provider status mapping is scaffolded in v1; queue/warm semantics are not mirrored from RunPod.",
    }


@router.post("/v1/models/{model_slug}/warm")
async def warm_model(
    model_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).where(LlmModel.slug == model_slug, LlmModel.status == "active"))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found or not active")

    provider = await resolve_model_provider(model, db)
    _require_provider_capability(provider, "supports_explicit_warm", f"Provider '{provider}' does not support explicit warm")

    if not model.runpod_endpoint_id:
        raise HTTPException(status_code=404, detail="Model endpoint not configured")

    try:
        await runpod_service.update_endpoint_idle_timeout(model.runpod_endpoint_id, 300)
    except Exception:
        pass

    import httpx

    url = f"{settings.runpod_base_url}/{model.runpod_endpoint_id}/run"
    headers = {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, headers=headers, json={"input": {"openai_route": "/v1/models", "openai_input": {}}})
    except Exception:
        pass
    return {"status": "warming", "provider": provider}


@router.post("/v1/models/{model_slug}/terminate")
async def terminate_model(
    model_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).where(LlmModel.slug == model_slug, LlmModel.status == "active"))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found or not active")

    provider = await resolve_model_provider(model, db)
    _require_provider_capability(provider, "supports_terminate", f"Provider '{provider}' does not support terminate in v1")

    if not model.runpod_endpoint_id:
        raise HTTPException(status_code=404, detail="Model endpoint not configured")

    await runpod_service.update_endpoint_idle_timeout(model.runpod_endpoint_id, 5)
    return {"status": "terminated", "message": "Worker will stop within seconds", "provider": provider}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    auth: tuple[User, ApiKey] = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    user, api_key = auth
    raw_body = await raw_request.body()
    debug_path = Path(f"/tmp/unchained_chat_body_{int(time.time() * 1000)}.json")
    debug_path.write_bytes(raw_body)
    print(f"CHAT_RAW_BODY_FILE: {debug_path}", flush=True)
    print(
        "CHAT_PARSED_SUMMARY:",
        json.dumps(
            {
                "model": request.model,
                "msgs": len(request.messages),
                "tools": len(request.tools or []),
                "tool_choice": request.tool_choice,
                "stream": request.stream,
                "max_tokens": request.max_tokens,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    allowed, retry_after = await check_rate_limit(str(api_key.id), user.tier)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(retry_after)})

    result = await db.execute(select(LlmModel).where(LlmModel.slug == request.model, LlmModel.status == "active"))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found or not active")

    provider = await resolve_model_provider(model, db)
    if provider == RUNPOD and not model.runpod_endpoint_id:
        raise HTTPException(status_code=503, detail=f"Model '{request.model}' endpoint not configured")
    if provider == MODAL and not model.deployment_ref:
        raise HTTPException(status_code=503, detail=f"Model '{request.model}' deployment not configured")

    max_ctx = model.max_context_length or 4096
    import json as _json

    tokens_in_estimate = count_message_tokens([{"role": m.role, "content": m.content} for m in request.messages])
    if request.tools:
        tools_tokens = count_message_tokens([{"role": "system", "content": _json.dumps(request.tools)}])
        tokens_in_estimate += tools_tokens

    safety_margin = max(256, int(tokens_in_estimate * 0.1))
    min_output = 16
    if tokens_in_estimate + safety_margin >= max_ctx - min_output:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Prompt too long: ~{tokens_in_estimate} input tokens, "
                f"model context is {max_ctx}. Reduce prompt or pick a model with larger context."
            ),
        )

    max_possible_output = max_ctx - tokens_in_estimate - safety_margin
    default_output = min(8192, max_possible_output)
    if request.max_tokens:
        request.max_tokens = min(request.max_tokens, max_possible_output)
    else:
        request.max_tokens = default_output

    gpu_hourly = float(model.gpu_hourly_cost or 0)
    margin = float(model.margin_multiplier or 1.5)
    estimated_cost = estimate_max_cost(request.max_tokens, gpu_hourly, margin)
    if not await check_credits(db, user.id, estimated_cost):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    if provider == MODAL:
        raise HTTPException(status_code=501, detail="Modal inference routing is not enabled yet; keep canary models pinned to RunPod.")

    if request.stream:
        return StreamingResponse(
            _stream_and_track(request, model, user, api_key, db),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    t_start = time.monotonic()
    response = await proxy_service.proxy_chat_completion(request, model)
    gpu_seconds = time.monotonic() - t_start

    actual_cost = calculate_gpu_cost(gpu_seconds, gpu_hourly, margin)
    await deduct_credits(db, user.id, actual_cost)
    await log_usage(
        db,
        user.id,
        api_key.id,
        model.id,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        actual_cost,
        gpu_seconds,
    )

    return response


async def _stream_and_track(
    request: ChatCompletionRequest,
    model: LlmModel,
    user: User,
    api_key: ApiKey,
    db: AsyncSession,
):
    gpu_hourly = float(model.gpu_hourly_cost or 0)
    margin = float(model.margin_multiplier or 1.5)

    full_output = []
    gpu_start = None

    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
            try:
                import json as _json

                data = _json.loads(chunk[6:])
                if data.get("object") == "status":
                    yield chunk
                    continue
                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if content:
                    if gpu_start is None:
                        gpu_start = time.monotonic()
                    full_output.append(content)
            except (ValueError, IndexError, KeyError):
                pass
        yield chunk

    gpu_end = time.monotonic()
    gpu_seconds = (gpu_end - gpu_start) if gpu_start else 0.0

    tokens_in = count_message_tokens([{"role": m.role, "content": m.content} for m in request.messages])
    tokens_out = count_message_tokens([{"role": "assistant", "content": "".join(full_output)}]) if full_output else 0

    actual_cost = calculate_gpu_cost(gpu_seconds, gpu_hourly, margin)
    await deduct_credits(db, user.id, actual_cost)
    await log_usage(db, user.id, api_key.id, model.id, tokens_in, tokens_out, actual_cost, gpu_seconds)
