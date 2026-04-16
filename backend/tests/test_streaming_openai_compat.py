import json

import pytest

from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse, ChatMessage
from app.services import proxy_service


@pytest.mark.asyncio
async def test_nonstream_tool_calls_force_finish_reason_tool_calls(monkeypatch):
    model = LlmModel(
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="endpoint-1",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    async def fake_run_inference(endpoint_id, payload):
        return {
            "output": [{
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "Bash", "arguments": "{\"command\":\"pwd\"}"}
                        }]
                    },
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            }]
        }

    monkeypatch.setattr("app.services.runpod_service.run_inference", fake_run_inference)

    response = await proxy_service.proxy_chat_completion(request, model)
    assert isinstance(response, ChatCompletionResponse)
    assert response.choices[0].message.tool_calls is not None
    assert response.choices[0].finish_reason == "tool_calls"

























































































































































































































































































































from app.services import proxy_service

@pytest.mark.asyncio
async def test_stream_emits_only_openai_chunks(monkeypatch):
    model = LlmModel(
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="endpoint-1",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    async def fake_stream_inference(endpoint_id, payload):
        yield "hello"

    async def fake_check_worker_status(endpoint_id):
        return {"ready": False, "status": "warming_up", "estimated_wait": 120}

    monkeypatch.setattr("app.services.runpod_service.stream_inference", fake_stream_inference)
    monkeypatch.setattr("app.services.runpod_service.check_worker_status", fake_check_worker_status)

    chunks = []
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        chunks.append(chunk)

    decoded = [c[6:] for c in chunks if c.startswith("data: ") and c.strip() != "data: [DONE]"]
    payloads = [json.loads(c) for c in decoded]

    assert all(p["object"] == "chat.completion.chunk" for p in payloads)
    assert all("choices" in p for p in payloads)


@pytest.mark.asyncio
async def test_stream_never_emits_object_status(monkeypatch):
    model = LlmModel(
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="endpoint-1",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    async def fake_stream_inference(endpoint_id, payload):
        yield '__STATUS:{"status":"IN_QUEUE","message":"Waiting","elapsed":10}'
        yield "hello"

    async def fake_check_worker_status(endpoint_id):
        return {"ready": False, "status": "idle", "estimated_wait": 60}

    monkeypatch.setattr("app.services.runpod_service.stream_inference", fake_stream_inference)
    monkeypatch.setattr("app.services.runpod_service.check_worker_status", fake_check_worker_status)

    chunks = []
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        chunks.append(chunk)

    decoded = [c[6:] for c in chunks if c.startswith("data: ") and c.strip() != "data: [DONE]"]
    assert all(json.loads(c).get("object") != "status" for c in decoded)
