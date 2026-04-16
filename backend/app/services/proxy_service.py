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


def _merge_system_prompts(model_prompt: str | None, messages: list[ChatMessage]) -> list[dict]:
    client_system_parts: list[str] = []
    non_system_messages: list[dict] = []

    for m in messages:
        if m.role == "system":
            if m.content:
                client_system_parts.append(m.content)
            continue

        item: dict = {"role": m.role, "content": m.content}
        if m.name:
            item["name"] = m.name
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = m.tool_calls
        non_system_messages.append(item)

    merged_parts: list[str] = []
    if model_prompt:
        merged_parts.append(model_prompt)
    if client_system_parts:
        merged_parts.append("\n\n---\n\n".join(client_system_parts))

    if merged_parts:
        return [{"role": "system", "content": "\n\n---\n\n".join(merged_parts)}, *non_system_messages]
    return non_system_messages


def _build_vllm_payload(request: ChatCompletionRequest, model: LlmModel, stream: bool = False) -> dict:
    """Transform OpenAI-format request into vLLM-compatible RunPod payload.

    When stream=True, vLLM returns SSE-formatted chunks which RunPod passes
    through via /stream endpoint. _extract_text in runpod_service handles parsing.
    stream=True is required for real-time token delivery (otherwise vLLM generates
    the entire response before returning, causing 60+ sec delays on thinking models).
    """
    messages_out = _merge_system_prompts(model.system_prompt, request.messages)

    payload: dict = {
        "model": model.hf_repo,
        "messages": messages_out,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens or 4096,
        "top_p": request.top_p,
        "stream": stream,
        "stop": request.stop,
    }

    # Pass-through of OpenAI-compatible extensions so tool-calling agents
    # (OpenClaude, Cline, Cursor, etc.) actually reach vLLM with their
    # function definitions.
    if request.tools:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = request.response_format
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.presence_penalty is not None:
        payload["presence_penalty"] = request.presence_penalty
    if request.frequency_penalty is not None:
        payload["frequency_penalty"] = request.frequency_penalty

    return {"openai_route": "/v1/chat/completions", "openai_input": payload}


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
        tool_calls = msg.get("tool_calls") or None
        finish_reason = c.get("finish_reason")
        if tool_calls and finish_reason in (None, "stop"):
            finish_reason = "tool_calls"
        choices.append(
            Choice(
                index=i,
                message=ChatMessage(
                    role=msg.get("role", "assistant"),
                    content=msg.get("content") or "",
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
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

    # Check worker status before starting inference.
    # Keep this for internal control flow only — do not emit custom status
    # objects in the OpenAI-compatible stream.
    worker_status = await runpod_service.check_worker_status(model.runpod_endpoint_id)

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

        # Drop internal status markers so the public stream stays strictly
        # OpenAI-compatible.
        if text_chunk.startswith("__STATUS:"):
            continue

        if not first_token_received:
            first_token_received = True

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
