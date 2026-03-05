from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.llm_model import LlmModel
from app.models.user import User
from app.services import keep_warm_service

router = APIRouter(tags=["keep-warm"])


async def _get_active_model(slug: str, db: AsyncSession) -> LlmModel:
    result = await db.execute(
        select(LlmModel).where(LlmModel.slug == slug, LlmModel.status == "active")
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{slug}' not found or not active")
    return model


@router.post("/v1/models/{slug}/keep-warm")
async def enable_keep_warm(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = await _get_active_model(slug, db)
    try:
        return await keep_warm_service.enable(db, user.id, model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/v1/models/{slug}/keep-warm")
async def disable_keep_warm(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = await _get_active_model(slug, db)
    return await keep_warm_service.disable(db, user.id, model)


@router.get("/v1/models/{slug}/keep-warm")
async def get_keep_warm_status(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = await _get_active_model(slug, db)
    return await keep_warm_service.get_status(db, user.id, model)
