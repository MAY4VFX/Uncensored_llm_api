import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.models.llm_model import LlmModel


@pytest.mark.asyncio
async def test_list_models(client: AsyncClient):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_chat_completion_no_auth(client: AsyncClient):
    resp = await client.post("/v1/chat/completions", json={
        "model": "some-model",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert resp.status_code == 422  # Missing auth header


@pytest.mark.asyncio
async def test_chat_completion_invalid_key(client: AsyncClient):
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "some-model",
            "messages": [{"role": "user", "content": "Hello"}],
        },
        headers={"Authorization": "Bearer sk-unch-invalidkey"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_admin_can_redeploy_active_model(client: AsyncClient, admin_headers, db_session, monkeypatch):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="old-endpoint",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add(model)
    await db_session.commit()

    monkeypatch.setattr("app.routers.admin.delete_endpoint", AsyncMock())
    monkeypatch.setattr(
        "app.routers.admin.create_endpoint",
        AsyncMock(return_value={"data": {"saveEndpoint": {"id": "new-endpoint"}}}),
    )

    response = await client.post(f"/admin/models/{model.id}/redeploy", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"detail": "Model redeployed", "endpoint_id": "new-endpoint"}

    await db_session.refresh(model)
    assert model.runpod_endpoint_id == "new-endpoint"
    assert model.status == "active"


@pytest.mark.asyncio
async def test_redeploy_returns_404_for_missing_model(client: AsyncClient, admin_headers):
    response = await client.post(
        "/admin/models/00000000-0000-0000-0000-000000000000/redeploy",
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Model not found"


@pytest.mark.asyncio
async def test_redeploy_marks_model_inactive_on_create_failure(client: AsyncClient, admin_headers, db_session, monkeypatch):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="broken-model",
        display_name="Broken Model",
        hf_repo="broken/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="old-endpoint",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add(model)
    await db_session.commit()

    monkeypatch.setattr("app.routers.admin.delete_endpoint", AsyncMock())
    monkeypatch.setattr("app.routers.admin.create_endpoint", AsyncMock(side_effect=RuntimeError("boom")))

    response = await client.post(f"/admin/models/{model.id}/redeploy", headers=admin_headers)

    assert response.status_code == 500
    assert response.json()["detail"] == "Deployment failed: boom"

    await db_session.refresh(model)
    assert model.status == "inactive"
    assert model.runpod_endpoint_id is None
