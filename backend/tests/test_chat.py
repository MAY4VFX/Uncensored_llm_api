import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatMessage
from app.services.proxy_service import _build_vllm_payload


@pytest.mark.asyncio
async def test_add_model_from_hf_uses_resolved_deploy_profile(client: AsyncClient, admin_headers, monkeypatch):
    fake_hf = {
        "id": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated",
        "tags": [
            "qwen3_moe",
            "abliterated",
            "uncensored",
            "base_model:Qwen/Qwen3-Coder-30B-A3B-Instruct",
        ],
        "siblings": [{"rfilename": "config.json"}],
        "cardData": {"base_model": ["Qwen/Qwen3-Coder-30B-A3B-Instruct"]},
        "downloads": 100,
        "likes": 10,
        "safetensors": {"total": 30_500_000_000},
    }

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return fake_hf

    async def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("app.routers.admin.httpx.AsyncClient.get", fake_get)

    response = await client.post(
        "/admin/models/add-from-hf",
        headers=admin_headers,
        json={"hf_repo": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["gpu_type"] == "H200_141GB"
    assert body["max_context_length"] >= 131072




@pytest.mark.asyncio
async def test_list_models(client: AsyncClient):


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


@pytest.mark.asyncio
async def test_build_vllm_payload_merges_model_prompt_and_client_system():
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
        system_prompt="Always answer in the user's language.",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[
            ChatMessage(role="system", content="Be concise."),
            ChatMessage(role="user", content="Привет"),
        ],
    )

    payload = _build_vllm_payload(request, model)
    messages = payload["openai_input"]["messages"]

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Always answer in the user's language.\n\n---\n\nBe concise."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Привет"


@pytest.mark.asyncio
async def test_build_vllm_payload_injects_model_prompt_when_client_has_no_system():
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
        system_prompt="Reply in the same language as the user.",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    payload = _build_vllm_payload(request, model)
    messages = payload["openai_input"]["messages"]

    assert messages[0] == {
        "role": "system",
        "content": "Reply in the same language as the user.",
    }
    assert messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_admin_can_update_model_system_prompt(client: AsyncClient, admin_headers, db_session):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="prompt-model",
        display_name="Prompt Model",
        hf_repo="prompt/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="inactive",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add(model)
    await db_session.commit()

    response = await client.patch(
        f"/admin/models/{model.id}",
        headers=admin_headers,
        json={"system_prompt": "Always answer in Russian."},
    )

    assert response.status_code == 200
    await db_session.refresh(model)
    assert model.system_prompt == "Always answer in Russian."
