from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.llm_model import LlmModel
from app.models.usage_log import UsageLog
from app.models.user import User
from app.schemas.usage import UsageLogEntry, UsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/me", response_model=UsageSummary)
async def my_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Aggregate totals
    totals = await db.execute(
        select(
            func.coalesce(func.sum(UsageLog.tokens_in), 0),
            func.coalesce(func.sum(UsageLog.tokens_out), 0),
            func.coalesce(func.sum(UsageLog.cost), 0),
        ).where(UsageLog.user_id == user.id)
    )
    total_in, total_out, total_cost = totals.one()

    # Recent usage (last 50 entries)
    recent = await db.execute(
        select(UsageLog, LlmModel.slug)
        .join(LlmModel, UsageLog.model_id == LlmModel.id)
        .where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc())
        .limit(50)
    )

    recent_entries = [
        UsageLogEntry(
            model_slug=slug,
            tokens_in=log.tokens_in,
            tokens_out=log.tokens_out,
            cost=float(log.cost),
            created_at=log.created_at,
        )
        for log, slug in recent.all()
    ]

    return UsageSummary(
        total_tokens_in=int(total_in),
        total_tokens_out=int(total_out),
        total_cost=float(total_cost),
        credits_remaining=float(user.credits),
        recent_usage=recent_entries,
    )
