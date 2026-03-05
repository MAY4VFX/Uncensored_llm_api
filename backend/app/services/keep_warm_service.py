import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keep_warm import KeepWarm
from app.models.llm_model import LlmModel
from app.services.credits_service import check_credits, deduct_credits
from app.services import runpod_service

logger = logging.getLogger(__name__)


async def enable(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    price = float(model.keep_warm_price)
    if price <= 0:
        raise ValueError("Keep warm is not available for this model")

    has_credits = await check_credits(db, user_id, price)
    if not has_credits:
        raise ValueError("Insufficient credits for at least 1 hour of keep warm")

    now = datetime.now(timezone.utc)
    stmt = insert(KeepWarm).values(
        user_id=user_id,
        model_id=model.id,
        is_active=True,
        activated_at=now,
        last_billed_at=now,
    ).on_conflict_do_update(
        index_elements=["user_id", "model_id"],
        set_=dict(is_active=True, activated_at=now, last_billed_at=now),
    )
    await db.execute(stmt)
    await db.commit()

    if model.runpod_endpoint_id:
        await runpod_service.update_endpoint_workers_min(model.runpod_endpoint_id, 1)

    return {"status": "enabled", "price_per_hour": price}


async def disable(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    await db.execute(
        update(KeepWarm)
        .where(KeepWarm.user_id == user_id, KeepWarm.model_id == model.id)
        .values(is_active=False)
    )
    await db.commit()

    # Check if anyone else is keeping this model warm
    result = await db.execute(
        select(func.count()).select_from(KeepWarm).where(
            KeepWarm.model_id == model.id, KeepWarm.is_active == True
        )
    )
    active_count = result.scalar()

    if active_count == 0 and model.runpod_endpoint_id:
        await runpod_service.update_endpoint_workers_min(model.runpod_endpoint_id, 0)

    return {"status": "disabled"}


async def get_status(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    result = await db.execute(
        select(KeepWarm).where(
            KeepWarm.user_id == user_id,
            KeepWarm.model_id == model.id,
            KeepWarm.is_active == True,
        )
    )
    record = result.scalar_one_or_none()
    return {
        "is_active": record is not None,
        "price_per_hour": float(model.keep_warm_price),
        "activated_at": record.activated_at.isoformat() if record else None,
    }


async def tick_billing(db: AsyncSession) -> None:
    """Bill all active keep_warm subscriptions. Called every 60s."""
    result = await db.execute(
        select(KeepWarm, LlmModel)
        .join(LlmModel, KeepWarm.model_id == LlmModel.id)
        .where(KeepWarm.is_active == True)
    )
    rows = result.all()

    now = datetime.now(timezone.utc)
    models_to_check: set[uuid.UUID] = set()

    for kw, model in rows:
        elapsed_seconds = (now - kw.last_billed_at).total_seconds()
        if elapsed_seconds < 30:
            continue

        amount = elapsed_seconds / 3600 * float(model.keep_warm_price)
        if amount <= 0:
            continue

        ok = await deduct_credits(db, kw.user_id, amount)
        if ok:
            await db.execute(
                update(KeepWarm)
                .where(KeepWarm.id == kw.id)
                .values(last_billed_at=now)
            )
            await db.commit()
        else:
            # Not enough credits — deactivate
            await db.execute(
                update(KeepWarm)
                .where(KeepWarm.id == kw.id)
                .values(is_active=False)
            )
            await db.commit()
            models_to_check.add(model.id)
            logger.info(f"Keep warm disabled for user {kw.user_id} model {model.slug}: insufficient credits")

    # For models where someone was deactivated, check if anyone else is still active
    for model_id in models_to_check:
        count_result = await db.execute(
            select(func.count()).select_from(KeepWarm).where(
                KeepWarm.model_id == model_id, KeepWarm.is_active == True
            )
        )
        if count_result.scalar() == 0:
            model_result = await db.execute(
                select(LlmModel).where(LlmModel.id == model_id)
            )
            model = model_result.scalar_one_or_none()
            if model and model.runpod_endpoint_id:
                try:
                    await runpod_service.update_endpoint_workers_min(model.runpod_endpoint_id, 0)
                except Exception as e:
                    logger.error(f"Failed to set workersMin=0 for {model.slug}: {e}")
