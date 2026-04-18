from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSettings
from app.models.llm_model import LlmModel

RUNPOD = "runpod"
MODAL = "modal"
SUPPORTED_PROVIDERS = {RUNPOD, MODAL}
DEFAULT_PROVIDER = MODAL


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_vllm: bool
    supports_gguf: bool
    supports_keep_warm: bool
    supports_explicit_warm: bool
    supports_terminate: bool
    supports_queue_status: bool
    supports_multigpu: bool


CAPABILITIES: dict[str, ProviderCapabilities] = {
    RUNPOD: ProviderCapabilities(
        supports_vllm=True,
        supports_gguf=True,
        supports_keep_warm=True,
        supports_explicit_warm=True,
        supports_terminate=True,
        supports_queue_status=True,
        supports_multigpu=True,
    ),
    MODAL: ProviderCapabilities(
        supports_vllm=True,
        supports_gguf=False,
        supports_keep_warm=False,
        supports_explicit_warm=False,
        supports_terminate=False,
        supports_queue_status=False,
        supports_multigpu=True,
    ),
}


async def get_or_create_app_settings(db: AsyncSession) -> AppSettings:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = AppSettings(id=1, default_provider=DEFAULT_PROVIDER, provider_flags={})
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings


async def get_default_provider(db: AsyncSession) -> str:
    settings = await get_or_create_app_settings(db)
    provider = settings.default_provider or DEFAULT_PROVIDER
    if provider not in SUPPORTED_PROVIDERS:
        return DEFAULT_PROVIDER
    return provider


async def resolve_model_provider(model: LlmModel, db: AsyncSession) -> str:
    if model.provider_override in SUPPORTED_PROVIDERS:
        return model.provider_override
    return await get_default_provider(db)


def get_provider_capabilities(provider: str) -> dict[str, Any]:
    caps = CAPABILITIES.get(provider, CAPABILITIES[RUNPOD])
    return {
        "supports_vllm": caps.supports_vllm,
        "supports_gguf": caps.supports_gguf,
        "supports_keep_warm": caps.supports_keep_warm,
        "supports_explicit_warm": caps.supports_explicit_warm,
        "supports_terminate": caps.supports_terminate,
        "supports_queue_status": caps.supports_queue_status,
        "supports_multigpu": caps.supports_multigpu,
    }


def normalize_provider_override(provider_override: str | None) -> str | None:
    if provider_override in SUPPORTED_PROVIDERS:
        return provider_override
    return None


def model_supports_provider_family(provider: str, family: str) -> bool:
    if provider == MODAL and family == "gguf":
        return False
    return True


def sync_resolve_model_provider(model: LlmModel, default_provider: str) -> str:
    if model.provider_override in SUPPORTED_PROVIDERS:
        return model.provider_override
    if default_provider in SUPPORTED_PROVIDERS:
        return default_provider
    return DEFAULT_PROVIDER
