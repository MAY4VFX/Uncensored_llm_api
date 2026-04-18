import uuid

import pytest

from app.models.llm_model import LlmModel
from app.services.provider_service import (
    DEFAULT_PROVIDER,
    MODAL,
    RUNPOD,
    get_default_provider,
    get_provider_capabilities,
    get_or_create_app_settings,
    normalize_provider_override,
    resolve_model_provider,
)


@pytest.mark.asyncio
async def test_get_or_create_app_settings_defaults_to_modal(db_session):
    settings = await get_or_create_app_settings(db_session)

    assert settings.id == 1
    assert settings.default_provider == DEFAULT_PROVIDER
    assert settings.default_provider == MODAL


@pytest.mark.asyncio
async def test_resolve_model_provider_prefers_override(db_session):
    await get_or_create_app_settings(db_session)
    model = LlmModel(
        id=uuid.uuid4(),
        slug="provider-test",
        display_name="Provider Test",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        provider_override=RUNPOD,
        status="inactive",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )

    provider = await resolve_model_provider(model, db_session)
    assert provider == RUNPOD


@pytest.mark.asyncio
async def test_get_default_provider_reads_settings(db_session):
    settings = await get_or_create_app_settings(db_session)
    settings.default_provider = RUNPOD
    await db_session.commit()

    provider = await get_default_provider(db_session)
    assert provider == RUNPOD


def test_normalize_provider_override_filters_invalid_values():
    assert normalize_provider_override(RUNPOD) == RUNPOD
    assert normalize_provider_override(MODAL) == MODAL
    assert normalize_provider_override("bogus") is None
    assert normalize_provider_override(None) is None


def test_provider_capabilities_capture_runpod_and_modal_difference():
    runpod = get_provider_capabilities(RUNPOD)
    modal = get_provider_capabilities(MODAL)

    assert runpod["supports_keep_warm"] is True
    assert runpod["supports_gguf"] is True
    assert modal["supports_vllm"] is True
    assert modal["supports_gguf"] is False
    assert modal["supports_keep_warm"] is False
