import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_model import LlmModel
from app.schemas.openai import OpenAIModel, OpenAIModelList

router = APIRouter(tags=["models"])


@router.get("/v1/models", response_model=OpenAIModelList)
async def list_models(db: AsyncSession = Depends(get_db)):
    """List available models in OpenAI-compatible format."""
    result = await db.execute(select(LlmModel).where(LlmModel.status == "active"))
    models = result.scalars().all()

    return OpenAIModelList(
        data=[
            OpenAIModel(
                id=m.slug,
                created=int(m.created_at.timestamp()) if m.created_at else int(time.time()),
            )
            for m in models
        ]
    )
