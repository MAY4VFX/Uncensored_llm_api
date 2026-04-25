import hashlib
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.models.api_key import ApiKey
from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatMessage
from app.services.proxy_service import _build_vllm_payload


@pytest.mark.asyncio
async def test_add_model_from_hf_uses_gpt_oss_profile(client: AsyncClient, admin_headers, monkeypatch):
    fake_hf = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "tags": [
            "gpt_oss",
            "abliterated",
            "uncensored",
            "reasoning",
            "base_model:openai/gpt-oss-120b",
        ],
        "siblings": [{"rfilename": "config.json"}],
        "cardData": {"base_model": ["openai/gpt-oss-120b"]},
        "downloads": 100,
        "likes": 10,
        "safetensors": {"total": 117_000_000_000},
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
        json={"hf_repo": "ArliAI/gpt-oss-120b-Derestricted"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["gpu_type"] == "H200_141GB"
    assert body["max_context_length"] >= 128000


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
    assert resp.status_code == 422


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
async def test_modal_gguf_tool_request_gets_short_default_max_tokens(client: AsyncClient, db_session, test_user, monkeypatch):
    raw_key = "sk-unch-" + "a" * 64
    api_key = ApiKey(
        user_id=test_user.id,
        key_prefix=raw_key[:16],
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        name="test",
    )
    model = LlmModel(
        id=uuid.uuid4(),
        slug="modal-gguf",
        display_name="Modal GGUF",
        hf_repo="Youssofal/Qwen3.6-27B-Abliterated-Heretic-Uncensored-GGUF",
        params_b=27,
        quantization="Q4_K_M",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        deployment_ref="https://modal.example",
        max_context_length=32768,
        provider_config={"provider": "modal", "family": "gguf"},
        gpu_hourly_cost=1.0,
        margin_multiplier=1.5,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add_all([api_key, model])
    await db_session.commit()

    captured = {}

    async def fake_run_chat(request, model):
        captured["max_tokens"] = request.max_tokens
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr("app.routers.chat.check_rate_limit", AsyncMock(return_value=(True, 0)))
    monkeypatch.setattr("app.routers.chat.modal_service.run_chat", fake_run_chat)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "modal-gguf",
            "messages": [{"role": "user", "content": "use tool"}],
            "tools": [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object"}}}],
        },
    )

    assert resp.status_code == 200
    assert captured["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_modal_gguf_keeps_explicit_max_tokens(client: AsyncClient, db_session, test_user, monkeypatch):
    raw_key = "sk-unch-" + "b" * 64
    api_key = ApiKey(
        user_id=test_user.id,
        key_prefix=raw_key[:16],
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        name="test",
    )
    model = LlmModel(
        id=uuid.uuid4(),
        slug="modal-gguf-explicit",
        display_name="Modal GGUF Explicit",
        hf_repo="Youssofal/Qwen3.6-27B-Abliterated-Heretic-Uncensored-GGUF",
        params_b=27,
        quantization="Q4_K_M",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        deployment_ref="https://modal.example",
        max_context_length=32768,
        provider_config={"provider": "modal", "family": "gguf"},
        gpu_hourly_cost=1.0,
        margin_multiplier=1.5,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add_all([api_key, model])
    await db_session.commit()

    captured = {}

    async def fake_run_chat(request, model):
        captured["max_tokens"] = request.max_tokens
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr("app.routers.chat.check_rate_limit", AsyncMock(return_value=(True, 0)))
    monkeypatch.setattr("app.routers.chat.modal_service.run_chat", fake_run_chat)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "modal-gguf-explicit",
            "messages": [{"role": "user", "content": "use tool"}],
            "tools": [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object"}}}],
            "max_tokens": 4096,
        },
    )

    assert resp.status_code == 200
    assert captured["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_redeploy_uses_gpt_oss_profile(client: AsyncClient, admin_headers, db_session, monkeypatch):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="test-model",
        display_name="Test Model",
        hf_repo="ArliAI/gpt-oss-120b-Derestricted",
        params_b=117,
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

    fake_hf = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "tags": [
            "gpt_oss",
            "abliterated",
            "uncensored",
            "reasoning",
            "base_model:openai/gpt-oss-120b",
        ],
        "siblings": [{"rfilename": "config.json"}],
        "cardData": {"base_model": ["openai/gpt-oss-120b"]},
        "safetensors": {"total": 117_000_000_000},
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
    monkeypatch.setattr("app.routers.admin.delete_endpoint", AsyncMock())
    mocked_create = AsyncMock(return_value={"data": {"saveEndpoint": {"id": "new-endpoint"}}})
    monkeypatch.setattr("app.routers.admin.create_endpoint", mocked_create)

    response = await client.post(f"/admin/models/{model.id}/redeploy", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"detail": "Model redeployed", "endpoint_id": "new-endpoint"}
    kwargs = mocked_create.await_args.kwargs
    assert kwargs["gpu_type"] == "H200_141GB"
    assert kwargs["gpu_count"] == 2
    assert kwargs["max_model_len"] >= 128000
    assert kwargs["tool_parser"] == "openai"
    assert kwargs["docker_image"] == "vllm/vllm-openai:v0.11.2"
    assert kwargs["generation_config_mode"] == "vllm"
    assert kwargs["runtime_args"]["tensor_parallel_size"] == 2
    assert kwargs["runtime_args"]["max_num_batched_tokens"] == 1024
    assert kwargs["default_temperature"] <= 0.2

    await db_session.refresh(model)
    assert model.gpu_type == "H200_141GB"
    assert model.max_context_length >= 128000
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
        hf_repo="ArliAI/gpt-oss-120b-Derestricted",
        params_b=117,
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

    fake_hf = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "tags": [
            "gpt_oss",
            "abliterated",
            "uncensored",
            "reasoning",
            "base_model:openai/gpt-oss-120b",
        ],
        "siblings": [{"rfilename": "config.json"}],
        "cardData": {"base_model": ["openai/gpt-oss-120b"]},
        "safetensors": {"total": 117_000_000_000},
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
    monkeypatch.setattr("app.routers.admin.delete_endpoint", AsyncMock())
    monkeypatch.setattr("app.routers.admin.create_endpoint", AsyncMock(side_effect=RuntimeError("boom")))

    response = await client.post(f"/admin/models/{model.id}/redeploy", headers=admin_headers)

    assert response.status_code == 500
    assert response.json()["detail"] == "Deployment failed: boom"

    await db_session.refresh(model)
    assert model.status == "inactive"
    assert model.runpod_endpoint_id is None


@pytest.mark.asyncio
async def test_create_endpoint_uses_openai_parser_and_larger_disk_for_gpt_oss(monkeypatch):
    from app.services import runpod_service

    captured_queries = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            if len(captured_queries) == 1:
                return {"data": {"saveTemplate": {"id": "tpl-1", "name": "tpl"}}}
            return {"data": {"saveEndpoint": {"id": "ep-1", "name": "ep", "gpuIds": "HOPPER_141", "templateId": "tpl-1"}}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured_queries.append(json["query"])
            return FakeResponse()

    monkeypatch.setattr(runpod_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await runpod_service.create_endpoint(
        name="unch-gpt-oss",
        gpu_type="H200_141GB",
        docker_image="vllm/vllm-openai:v0.11.2",
        model_name="ArliAI/gpt-oss-120b-Derestricted",
        params_b=117.0,
        max_model_len=128000,
        gpu_count=2,
        tool_parser="openai",
        generation_config_mode="vllm",
        default_temperature=0.2,
        runtime_args={"tensor_parallel_size": 2, "max_num_batched_tokens": 1024},
    )

    assert result["data"]["saveEndpoint"]["id"] == "ep-1"
    template_query = captured_queries[0]
    endpoint_query = captured_queries[1]
    assert 'imageName: "vllm/vllm-openai:v0.11.2"' in template_query
    assert 'TOOL_CALL_PARSER", value: "openai"' in template_query
    assert 'MAX_MODEL_LEN", value: "128000"' in template_query
    assert 'MODEL_NAME", value: "ArliAI/gpt-oss-120b-Derestricted"' in template_query
    assert 'dockerArgs: "--model ArliAI/gpt-oss-120b-Derestricted --host 0.0.0.0 --port 8000 --max-model-len 128000 --tool-call-parser openai --enable-auto-tool-choice --tensor-parallel-size 2 --max-num-batched-tokens 1024"' in template_query
    assert 'gpuCount: 2' in endpoint_query
    assert "containerDiskInGb: 300" in template_query


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
