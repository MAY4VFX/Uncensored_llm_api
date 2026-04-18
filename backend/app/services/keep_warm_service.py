import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keep_warm import KeepWarm
from app.models.llm_model import LlmModel
from app.services import modal_service, runpod_service
from app.services.credits_service import check_credits, deduct_credits
from app.services.provider_service import MODAL, RUNPOD, resolve_model_provider
from app.services.runpod_service import GPU_HOURLY_COST

logger = logging.getLogger(__name__)

KEEP_WARM_MARGIN = 1.15


def get_keep_warm_price(model: LlmModel) -> float:
    if float(model.keep_warm_price) > 0:
        return float(model.keep_warm_price)

    gpu_cost = float(model.gpu_hourly_cost)
    if gpu_cost <= 0:
        gpu_cost = GPU_HOURLY_COST.get(model.gpu_type, 0)

    return round(gpu_cost * KEEP_WARM_MARGIN, 4)


async def _supports_keep_warm(db: AsyncSession, model: LlmModel) -> bool:
    provider = await resolve_model_provider(model, db)
    if provider == RUNPOD:
        return bool(model.runpod_endpoint_id)
    if provider == MODAL:
        return bool((model.provider_config or {}).get("app_name"))
    return False


async def _provider_payload(db: AsyncSession, model: LlmModel) -> dict:
    provider = await resolve_model_provider(model, db)
    supported = await _supports_keep_warm(db, model)
    message = None if supported else f"Keep warm is not available for provider '{provider}'"
    return {
        "provider": provider,
        "supported": supported,
        "message": message,
    }


async def _sync_workers_min(db: AsyncSession, model: LlmModel) -> int:
    result = await db.execute(
        select(func.count()).select_from(KeepWarm).where(
            KeepWarm.model_id == model.id,
            KeepWarm.is_active == True,
        )
    )
    active_count = result.scalar() or 0

    if await _supports_keep_warm(db, model):
        provider = await resolve_model_provider(model, db)
        try:
            if provider == RUNPOD:
                await runpod_service.update_endpoint_workers_min(model.runpod_endpoint_id, active_count)
            elif provider == MODAL:
                await modal_service.update_min_containers(model, active_count)
        except Exception as e:
            logger.error(f"Failed to set min={active_count} for {model.slug}: {e}")

    return active_count


async def _require_supported(db: AsyncSession, model: LlmModel) -> None:
    if await _supports_keep_warm(db, model):
        return
    provider = await resolve_model_provider(model, db)
    raise ValueError(f"Keep warm is not available for provider '{provider}' in v1")


async def enable(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    await _require_supported(db, model)

    price = get_keep_warm_price(model)
    if price <= 0:
        raise ValueError("Keep warm is not available for this model — GPU cost unknown")

    has_credits = await check_credits(db, user_id, price)
    if not has_credits:
        raise ValueError("Insufficient credits for at least 1 hour of keep warm")

    now = datetime.now(timezone.utc)
    existing = await db.execute(
        select(KeepWarm).where(KeepWarm.user_id == user_id, KeepWarm.model_id == model.id)
    )
    record = existing.scalar_one_or_none()

    if record:
        if record.is_active:
            workers = await _sync_workers_min(db, model)
            return {
                "status": "already_enabled",
                "price_per_hour": price,
                "warm_workers": workers,
                **(await _provider_payload(db, model)),
            }
        await db.execute(
            update(KeepWarm)
            .where(KeepWarm.user_id == user_id, KeepWarm.model_id == model.id)
            .values(is_active=True, activated_at=now, last_billed_at=now)
        )
    else:
        db.add(
            KeepWarm(
                user_id=user_id,
                model_id=model.id,
                is_active=True,
                activated_at=now,
                last_billed_at=now,
            )
        )
    await db.commit()

    workers = await _sync_workers_min(db, model)
    return {
        "status": "enabled",
        "price_per_hour": price,
        "warm_workers": workers,
        **(await _provider_payload(db, model)),
    }


async def disable(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    await _require_supported(db, model)

    await db.execute(
        update(KeepWarm)
        .where(KeepWarm.user_id == user_id, KeepWarm.model_id == model.id)
        .values(is_active=False)
    )
    await db.commit()

    workers = await _sync_workers_min(db, model)
    return {
        "status": "disabled",
        "warm_workers": workers,
        **(await _provider_payload(db, model)),
    }


async def get_status(db: AsyncSession, user_id: uuid.UUID, model: LlmModel) -> dict:
    if not await _supports_keep_warm(db, model):
        return {
            "is_active": False,
            "price_per_hour": get_keep_warm_price(model),
            "activated_at": None,
            "warm_workers": 0,
            **(await _provider_payload(db, model)),
        }

    result = await db.execute(
        select(KeepWarm).where(
            KeepWarm.user_id == user_id,
            KeepWarm.model_id == model.id,
            KeepWarm.is_active == True,
        )
    )
    record = result.scalar_one_or_none()

    count_result = await db.execute(
        select(func.count()).select_from(KeepWarm).where(
            KeepWarm.model_id == model.id,
            KeepWarm.is_active == True,
        )
    )
    warm_workers = count_result.scalar() or 0

    return {
        "is_active": record is not None,
        "price_per_hour": get_keep_warm_price(model),
        "activated_at": record.activated_at.isoformat() if record else None,
        "warm_workers": warm_workers,
        **(await _provider_payload(db, model)),
    }


async def tick_billing(db: AsyncSession) -> None:
    result = await db.execute(
        select(KeepWarm, LlmModel)
        .join(LlmModel, KeepWarm.model_id == LlmModel.id)
        .where(KeepWarm.is_active == True)
    )
    rows = result.all()

    now = datetime.now(timezone.utc)
    models_to_check: set[uuid.UUID] = set()

    for kw, model in rows:
        provider = await resolve_model_provider(model, db)
        if provider not in (RUNPOD, MODAL):
            continue

        elapsed_seconds = (now - kw.last_billed_at).total_seconds()
        if elapsed_seconds < 30:
            continue

        amount = elapsed_seconds / 3600 * get_keep_warm_price(model)
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
            await db.execute(
                update(KeepWarm)
                .where(KeepWarm.id == kw.id)
                .values(is_active=False)
            )
            await db.commit()
            models_to_check.add(model.id)
            logger.info(f"Keep warm disabled for user {kw.user_id} model {model.slug}: insufficient credits")

    for model_id in models_to_check:
        model_result = await db.execute(select(LlmModel).where(LlmModel.id == model_id))
        model = model_result.scalar_one_or_none()
        if model:
            await _sync_workers_min(db, model)
