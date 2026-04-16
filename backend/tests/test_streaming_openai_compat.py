import json

import pytest

from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse, ChatMessage
from app.services import proxy_service, runpod_service


def test_normalize_tool_call_arguments_unwraps_double_encoded_json():
    """vLLM qwen3_coder streaming returns arguments as JSON-encoded strings;
    we must collapse them back to plain JSON-object strings.
    """
    src = '"{\\"filePath\\": \\"/tmp/x.txt\\"}"'
    out = runpod_service._normalize_tool_call_arguments(src)
    assert out == '{"filePath": "/tmp/x.txt"}'


def test_normalize_tool_call_arguments_passes_normal_json_through():
    src = '{"filePath": "/tmp/x.txt"}'
    assert runpod_service._normalize_tool_call_arguments(src) == src


def test_normalize_tool_call_arguments_passes_partial_chunk_through():
    """Streaming may emit incremental fragments — leave them alone."""
    assert runpod_service._normalize_tool_call_arguments('{"filePath') == '{"filePath'
    assert runpod_service._normalize_tool_call_arguments('') == ''


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


@pytest.mark.asyncio
async def test_stream_forwards_tool_calls_from_vllm_chunks(monkeypatch):
    """When vLLM emits delta.tool_calls, the proxy must forward them in the
    OpenAI stream — extracting only `content` would silently drop tool calls
    and leave agents (opencode, OpenClaude) unable to invoke any tool."""
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
        messages=[ChatMessage(role="user", content="read the log file")],
        tools=[{"type": "function", "function": {"name": "read"}}],
        tool_choice="auto",
        stream=True,
    )

    async def fake_stream_inference(endpoint_id, payload):
        # Simulate the vLLM SSE chunk dicts that arrive via runpod_service.
        # The stream_inference contract is: yield "__CHUNK:<json>" for every
        # structured chunk (delta) and "__STATUS:..." for queue updates.
        yield "__CHUNK:" + json.dumps({
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None,
            }]
        })
        yield "__CHUNK:" + json.dumps({
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read", "arguments": ""},
                    }]
                },
                "finish_reason": None,
            }]
        })
        yield "__CHUNK:" + json.dumps({
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": "{\"filePath\":\"/tmp/x\"}"},
                    }]
                },
                "finish_reason": None,
            }]
        })
        yield "__CHUNK:" + json.dumps({
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "tool_calls",
            }]
        })

    async def fake_check_worker_status(endpoint_id):
        return {"ready": True, "status": "ready", "estimated_wait": 0}

    monkeypatch.setattr("app.services.runpod_service.stream_inference", fake_stream_inference)
    monkeypatch.setattr("app.services.runpod_service.check_worker_status", fake_check_worker_status)

    chunks = []
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        chunks.append(chunk)

    decoded = [json.loads(c[6:]) for c in chunks if c.startswith("data: ") and c.strip() != "data: [DONE]"]
    tool_call_seen = False
    finish_reasons = []
    for d in decoded:
        for ch in d.get("choices", []):
            delta = ch.get("delta") or {}
            if delta.get("tool_calls"):
                tool_call_seen = True
            if ch.get("finish_reason"):
                finish_reasons.append(ch["finish_reason"])
    assert tool_call_seen, "tool_calls must be forwarded as delta.tool_calls"
    assert "tool_calls" in finish_reasons, "finish_reason=tool_calls must appear"
    # No synthetic duplicate "stop" finish chunk after vLLM finished
    assert finish_reasons.count("stop") == 0
