import json
from unittest.mock import AsyncMock

import pytest

from app.services import modal_service


class DummyModel:
    hf_repo = "test/model"
    gpu_type = "H100_80GB"
    gpu_count = 1
    max_context_length = 4096
    slug = "test-model"
    provider_config = {"app_name": "unchained-test-model", "function_name": "openai_api", "web_url": "https://example.modal.run"}
    deployment_ref = "app-123"


def test_supports_runtime_rejects_gguf():
    assert modal_service.supports_runtime({"family": "gguf"}) is False
    assert modal_service.supports_runtime({"family": "qwen3_coder"}) is True


def test_modal_gpu_mapping_prefers_modal_labels():
    assert modal_service._modal_gpu_value("H100_80GB") == "H100"
    assert modal_service._modal_gpu_value("H200_141GB") == "H100"
    assert modal_service._modal_gpu_value("A100_80GB") == "A100-80GB"


@pytest.mark.asyncio
async def test_get_status_uses_health_probe(monkeypatch):
    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            assert url == "https://example.modal.run/health"
            return FakeResponse()

    monkeypatch.setattr(modal_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    status = await modal_service.get_status(DummyModel())

    assert status["status"] == "ready"
    assert status["workers_ready"] == 1


@pytest.mark.asyncio
async def test_run_chat_posts_openai_payload(monkeypatch):
    class Request:
        temperature = 0.2
        max_tokens = 128
        top_p = 1.0
        tools = None
        tool_choice = None
        response_format = None
        messages = [type("Msg", (), {"role": "user", "content": "Hello"})()]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None):
            assert url == "https://example.modal.run/v1/chat/completions"
            assert json["stream"] is False
            assert json["messages"][0]["content"] == "Hello"
            return FakeResponse()

    monkeypatch.setattr(modal_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await modal_service.run_chat(Request(), DummyModel())
    assert result["choices"][0]["message"]["content"] == "Hi"


@pytest.mark.asyncio
async def test_stream_chat_yields_text_chunks(monkeypatch):
    class Request:
        temperature = 0.2
        max_tokens = 128
        top_p = 1.0
        tools = None
        tool_choice = None
        response_format = None
        messages = [type("Msg", (), {"role": "user", "content": "Hello"})()]

    class FakeResponse:
        def raise_for_status(self):
            return None

        async def aiter_text(self):
            for item in ["data: {\"choices\":[{\"delta\":{\"content\":\"Hi\"}}]}\n\n", "data: [DONE]\n\n"]:
                yield item

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json=None):
            assert method == "POST"
            assert url == "https://example.modal.run/v1/chat/completions"
            assert json["stream"] is True
            return FakeStream()

    monkeypatch.setattr(modal_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    chunks = []
    async for chunk in modal_service.stream_chat(Request(), DummyModel()):
        chunks.append(chunk)

    assert any("Hi" in chunk for chunk in chunks)
    assert any("[DONE]" in chunk for chunk in chunks)
