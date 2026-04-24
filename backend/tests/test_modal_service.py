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


def test_supports_runtime_accepts_gguf():
    assert modal_service.supports_runtime({"family": "gguf"}) is True
    assert modal_service.supports_runtime({"family": "qwen3_coder"}) is True
    assert modal_service.supports_runtime({"family": ""}) is False


def test_modal_gpu_mapping_prefers_modal_labels():
    assert modal_service._modal_gpu_value("H100_80GB") == "H100"
    assert modal_service._modal_gpu_value("H200_141GB") == "H200"
    assert modal_service._modal_gpu_value("A100_80GB") == "A100-80GB"


def test_modal_name_sanitization_is_dns_safe_and_short():
    name = modal_service._sanitize_modal_part("Unchained/Qwen 3.6 GGUF !!!" * 4, "fallback")
    assert len(name) <= 63
    assert name == name.lower()
    assert "/" not in name
    assert " " not in name


@pytest.mark.asyncio
async def test_modal_env_for_gguf_uses_llamacpp_image_over_default(monkeypatch):
    async def fake_resolve(repo):
        assert repo == "test/model"
        return {"gguf_file": "model-Q4_K_M.gguf", "base_model": "Qwen/Qwen3", "has_config": True}

    monkeypatch.setattr(modal_service, "_resolve_gguf", fake_resolve)

    env = await modal_service._modal_env(
        DummyModel(),
        {"family": "gguf", "target_context": 8192},
        default_image="vllm/vllm-openai:v0.19.1",
    )

    assert env["MODAL_MODEL_FAMILY"] == "gguf"
    assert env["MODAL_GGUF_RUNTIME"] == "llamacpp"
    assert env["MODAL_GGUF_FILE"] == "model-Q4_K_M.gguf"
    assert env["MODAL_GGUF_BASE_MODEL"] == "Qwen/Qwen3"
    assert env["MODAL_GGUF_HAS_CONFIG"] == "true"
    assert env["MODAL_RUNTIME_IMAGE"] == "ghcr.io/ggml-org/llama.cpp:server-cuda"
    assert env["MODAL_LLAMA_SERVER_BINARY"] == "llama-server"
    assert env["MODAL_LOCAL_LLAMA_PORT"] == "8001"
    runtime_args = __import__("json").loads(env["MODAL_RUNTIME_ARGS_JSON"])
    assert runtime_args["gguf_file"] == "model-Q4_K_M.gguf"
    assert runtime_args["ngl"] == 999
    assert runtime_args["jinja"] is True


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
async def test_run_chat_accumulates_sse_stream(monkeypatch):
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
            for item in [
                'data: {"id":"chatcmpl-test","created":1,"model":"test-model","choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}' + "\n\n",
                'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}' + "\n\n",
                "data: [DONE]\n\n",
            ]:
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
            assert json["messages"][0]["content"] == "Hello"
            return FakeStream()

    monkeypatch.setattr(modal_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await modal_service.run_chat(Request(), DummyModel())
    assert result["choices"][0]["message"]["content"] == "Hi"
    assert result["usage"]["total_tokens"] == 2


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
