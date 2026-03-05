from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, verify_api_key
from app.middleware.rate_limiter import check_rate_limit
from app.models.api_key import ApiKey
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse
from app.services import proxy_service, runpod_service
from app.config import settings
from app.services.credits_service import check_credits, deduct_credits
from app.services.usage_service import calculate_cost, count_message_tokens, log_usage

router = APIRouter(tags=["chat"])


@router.get("/v1/models/{model_slug}/status")
async def model_status(
    model_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Check worker status for a model (ready/cold/warming_up/throttled)."""
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == model_slug, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_slug}' not found or not active")

    if not model.runpod_endpoint_id:
        return {"status": "unavailable", "estimated_wait_seconds": 0, "message": "Endpoint not configured"}

    worker = await runpod_service.check_worker_status(model.runpod_endpoint_id)
    return {
        "status": worker["status"],
        "estimated_wait_seconds": worker["estimated_wait"],
        "workers_ready": worker["workers_ready"],
    }


@router.post("/v1/models/{model_slug}/warm")
async def warm_model(
    model_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger worker wake-up without waiting for full inference."""
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == model_slug, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model or not model.runpod_endpoint_id:
        raise HTTPException(status_code=404, detail="Model not found or endpoint not configured")

    import httpx
    url = f"{settings.runpod_base_url}/{model.runpod_endpoint_id}/run"
    headers = {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, headers=headers, json={
                "input": {"openai_route": "/v1/models", "openai_input": {}}
            })
    except Exception:
        pass  # Fire-and-forget: don't fail if RunPod is slow
    return {"status": "warming"}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    auth: tuple[User, ApiKey] = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    user, api_key = auth

    # 1. Rate limit check
    allowed, retry_after = await check_rate_limit(str(api_key.id), user.tier)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Lookup model
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == request.model, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found or not active")

    if not model.runpod_endpoint_id:
        raise HTTPException(status_code=503, detail=f"Model '{request.model}' endpoint not configured")

    # 2b. Validate max_tokens against model context limit
    max_ctx = model.max_context_length or 4096

    # 3. Estimate cost and check credits
    tokens_in_estimate = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )

    # Cap max_tokens so prompt + completion fits within context window
    max_possible_output = max(1, max_ctx - tokens_in_estimate)
    if request.max_tokens:
        request.max_tokens = min(request.max_tokens, max_possible_output)
    else:
        request.max_tokens = max_possible_output

    estimated_cost = calculate_cost(
        tokens_in_estimate,
        request.max_tokens,
        float(model.cost_per_1m_input),
        float(model.cost_per_1m_output),
    )

    if not await check_credits(db, user.id, estimated_cost):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    # 4. Proxy to RunPod
    if request.stream:
        return StreamingResponse(
            _stream_and_track(request, model, user, api_key, db),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    # Non-streaming
    response = await proxy_service.proxy_chat_completion(request, model)

    # 5. Track usage
    actual_cost = calculate_cost(
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        float(model.cost_per_1m_input),
        float(model.cost_per_1m_output),
    )
    await deduct_credits(db, user.id, actual_cost)
    await log_usage(
        db, user.id, api_key.id, model.id,
        response.usage.prompt_tokens, response.usage.completion_tokens, actual_cost,
    )

    return response


async def _stream_and_track(
    request: ChatCompletionRequest,
    model: LlmModel,
    user: User,
    api_key: ApiKey,
    db: AsyncSession,
):
    """Stream response and track usage after completion."""
    total_output_tokens = 0
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        # Rough token count for streaming
        if "content" in chunk and chunk != "data: [DONE]\n\n":
            total_output_tokens += 1
        yield chunk

    # Track usage after stream completes
    tokens_in = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    actual_cost = calculate_cost(
        tokens_in, total_output_tokens,
        float(model.cost_per_1m_input), float(model.cost_per_1m_output),
    )
    await deduct_credits(db, user.id, actual_cost)
    await log_usage(db, user.id, api_key.id, model.id, tokens_in, total_output_tokens, actual_cost)
