"""Playground chat endpoint — allows authenticated users to test models via JWT (no API key required)."""

import json
import time
import uuid

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
from app.services.usage_service import calculate_cost, count_message_tokens

router = APIRouter(prefix="/playground", tags=["playground"])


@router.post("/chat")
async def playground_chat(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Chat endpoint for the playground — uses JWT auth instead of API key."""
    # Lookup model
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == request.model, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found or not active")

    if not model.runpod_endpoint_id:
        raise HTTPException(status_code=503, detail=f"Model '{request.model}' endpoint not configured")

    # Check credits
    tokens_in_estimate = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    estimated_cost = calculate_cost(
        tokens_in_estimate, request.max_tokens or 2048,
        float(model.cost_per_1m_input), float(model.cost_per_1m_output),
    )
    if not await check_credits(db, user.id, estimated_cost):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    # Always stream for playground
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
    """Stream response for playground use."""
    total_output_tokens = 0
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        if "content" in chunk and chunk != "data: [DONE]\n\n":
            total_output_tokens += 1
        yield chunk

    # Track usage
    tokens_in = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )
    actual_cost = calculate_cost(
        tokens_in, total_output_tokens,
        float(model.cost_per_1m_input), float(model.cost_per_1m_output),
    )
    await deduct_credits(db, user.id, actual_cost)
