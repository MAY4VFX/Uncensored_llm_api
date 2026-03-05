"""Playground chat endpoint — allows authenticated users to test models via JWT (no API key required)."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.openai import ChatCompletionRequest
from app.services import proxy_service
from app.services.credits_service import check_credits, deduct_credits
from app.services.usage_service import (
    calculate_gpu_cost, count_message_tokens, estimate_max_cost, log_usage,
)

router = APIRouter(prefix="/playground", tags=["playground"])


@router.post("/chat")
async def playground_chat(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Chat endpoint for the playground — uses JWT auth instead of API key."""
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == request.model, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found or not active")

    if not model.runpod_endpoint_id:
        raise HTTPException(status_code=503, detail=f"Model '{request.model}' endpoint not configured")

    tokens_in_estimate = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    max_ctx = model.max_context_length or 4096

    max_possible_output = max(1, max_ctx - tokens_in_estimate)
    if request.max_tokens:
        request.max_tokens = min(request.max_tokens, max_possible_output)
    else:
        request.max_tokens = max_possible_output

    # Pre-auth: estimate max GPU cost
    gpu_hourly = float(model.gpu_hourly_cost or 0)
    margin = float(model.margin_multiplier or 1.5)
    estimated_cost = estimate_max_cost(request.max_tokens, gpu_hourly, margin)

    if not await check_credits(db, user.id, estimated_cost):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    return StreamingResponse(
        _stream_playground(request, model, user, db),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _stream_playground(
    request: ChatCompletionRequest,
    model: LlmModel,
    user: User,
    db: AsyncSession,
):
    """Stream response and bill by GPU time."""
    gpu_hourly = float(model.gpu_hourly_cost or 0)
    margin = float(model.margin_multiplier or 1.5)

    full_output = []
    gpu_start = None

    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
            try:
                data = json.loads(chunk[6:])
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

    tokens_in = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    tokens_out = count_message_tokens(
        [{"role": "assistant", "content": "".join(full_output)}]
    ) if full_output else 0

    actual_cost = calculate_gpu_cost(gpu_seconds, gpu_hourly, margin)
    await deduct_credits(db, user.id, actual_cost)
    await log_usage(db, user.id, None, model.id, tokens_in, tokens_out, actual_cost, gpu_seconds)
