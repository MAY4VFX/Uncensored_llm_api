import json
import time
import uuid
from typing import AsyncGenerator

from app.models.llm_model import LlmModel
from app.schemas.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    DeltaMessage,
    StreamChoice,
    Usage,
)
from app.services import runpod_service


def _status_message(status: str) -> str:
    """Human-readable message for worker status."""
    messages = {
        "cold": "Model is cold, worker starting up... Please wait ~2-3 minutes.",
        "warming_up": "Worker is initializing... Please wait ~1-2 minutes.",
        "throttled": "Workers are throttled due to high demand. Please wait ~3-5 minutes.",
    }
    return messages.get(status, "Preparing worker...")


def _build_vllm_payload(request: ChatCompletionRequest, model: LlmModel, stream: bool = False) -> dict:
    """Transform OpenAI-format request into vLLM-compatible RunPod payload.

    When stream=True, vLLM returns SSE-formatted chunks which RunPod passes
    through via /stream endpoint. _extract_text in runpod_service handles parsing.
    stream=True is required for real-time token delivery (otherwise vLLM generates
    the entire response before returning, causing 60+ sec delays on thinking models).
    """
    return {
        "openai_route": "/v1/chat/completions",
        "openai_input": {
            "model": model.hf_repo,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 2048,
            "top_p": request.top_p,
            "stream": stream,
            "stop": request.stop,
        },
    }


async def proxy_chat_completion(
    request: ChatCompletionRequest, model: LlmModel
) -> ChatCompletionResponse:
    """Proxy a non-streaming chat completion request to RunPod."""
    payload = _build_vllm_payload(request, model)
    result = await runpod_service.run_inference(model.runpod_endpoint_id, payload)

    # Parse RunPod/vLLM response
    output = result.get("output", result)
    if isinstance(output, str):
        output = json.loads(output)
    # RunPod wraps vLLM output in a list
    if isinstance(output, list) and len(output) > 0:
        output = output[0]

    # Handle vLLM OpenAI-compat response format
    choices_data = output.get("choices", []) if isinstance(output, dict) else []
    usage_data = output.get("usage", {}) if isinstance(output, dict) else {}

    choices = []
    for i, c in enumerate(choices_data):
        msg = c.get("message", {})
        choices.append(
            Choice(
                index=i,
                message=ChatMessage(role=msg.get("role", "assistant"), content=msg.get("content", "")),
                finish_reason=c.get("finish_reason"),
            )
        )

    if not choices:
        # Fallback: raw text output
        text = output.get("text", output.get("result", str(output)))
        choices = [
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=text),
                finish_reason="stop",
            )
        ]

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=request.model,
        choices=choices,
        usage=Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        ),
    )


async def proxy_chat_completion_stream(
    request: ChatCompletionRequest, model: LlmModel
) -> AsyncGenerator[str, None]:
    """Proxy a streaming chat completion request to RunPod via SSE."""
    payload = _build_vllm_payload(request, model, stream=True)
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    # Check worker status before starting inference
    worker_status = await runpod_service.check_worker_status(model.runpod_endpoint_id)
    if not worker_status["ready"]:
        status_event = {
            "object": "status",
            "status": worker_status["status"],
            "message": _status_message(worker_status["status"]),
            "estimated_wait": worker_status["estimated_wait"],
        }
        yield f"data: {json.dumps(status_event)}\n\n"

    # Send initial role chunk
    initial_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=request.model,
        choices=[StreamChoice(index=0, delta=DeltaMessage(role="assistant"), finish_reason=None)],
    )
    yield f"data: {initial_chunk.model_dump_json()}\n\n"

    # Stream content from RunPod
    first_token_received = False
    async for text_chunk in runpod_service.stream_inference(model.runpod_endpoint_id, payload):
        if not text_chunk:
            continue

        # Handle status markers from stream_inference (queue/progress updates)
        if text_chunk.startswith("__STATUS:"):
            status_data = json.loads(text_chunk[9:])
            status_event = {
                "object": "status",
                "status": status_data.get("status", "unknown"),
                "message": status_data.get("message", ""),
                "elapsed": status_data.get("elapsed", 0),
            }
            yield f"data: {json.dumps(status_event)}\n\n"
            continue

        # First real token — send ready event if worker was cold
        if not first_token_received:
            first_token_received = True
            if not worker_status["ready"]:
                ready_event = {"object": "status", "status": "ready", "message": "Worker ready, generating..."}
                yield f"data: {json.dumps(ready_event)}\n\n"

        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[StreamChoice(index=0, delta=DeltaMessage(content=text_chunk), finish_reason=None)],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"

    # Send finish chunk
    finish_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=request.model,
        choices=[StreamChoice(index=0, delta=DeltaMessage(), finish_reason="stop")],
    )
    yield f"data: {finish_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
