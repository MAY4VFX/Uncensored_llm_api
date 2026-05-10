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

    # Thinking control: default OFF on thinking-capable models so plain
    # OpenAI-compatible clients (OpenClaude, Cline, OpenWebUI, LangChain)
    # get content + tool_calls instead of reasoning that their parser
    # silently drops. Client always wins: if it sends any of the three
    # knobs, we forward verbatim and skip server-side defaults.
    hf_repo_lower = (model.hf_repo or "").lower()
    is_qwen3_thinking = (
        "qwen3.5" in hf_repo_lower or "qwen3.6" in hf_repo_lower
    )
    is_gpt_oss = "gpt-oss" in hf_repo_lower
    client_template = request.chat_template_kwargs
    client_effort = request.reasoning_effort
    client_budget = request.reasoning_budget
    if client_template is not None:
        payload["chat_template_kwargs"] = client_template
    if client_effort is not None:
        payload["reasoning_effort"] = client_effort
    if client_budget is not None:
        payload["reasoning_budget"] = client_budget
    if all(x is None for x in (client_template, client_effort, client_budget)):
        if is_qwen3_thinking:
            # Only enable_thinking actually turns thinking off for the
            # Qwen3 chat template; reasoning_effort isn't mapped here.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        elif is_gpt_oss:
            payload["reasoning_effort"] = "low"
            payload["reasoning_budget"] = 256

    # Patch for GPT-OSS harmony parser crashes.
    # OpenAI's gpt-oss release treats BOTH `<|return|>` (199999) AND `<|call|>`
    # (200012) as EOS tokens (see openai/gpt-oss HF commit #105, 2025-08-13).
    # Community forks (ArliAI/Derestricted, etc.) frequently ship a
    # generation_config.json that forgot 200012 — so the model never stops on
    # tool-call boundary, keeps generating malformed harmony tokens, and
    # openai_harmony raises `HarmonyError: Unexpected token ... while
    # expecting start token 200006` (vLLM issues #27243, #22578). Injecting
    # 200012 as a stop token in sampling params forces vLLM to end generation
    # at the same point OpenAI intended, regardless of the model repo's EOS.
    hf_repo_lower = (model.hf_repo or "").lower()
    if "gpt-oss" in hf_repo_lower or "gpt_oss" in hf_repo_lower:
        existing = payload.get("stop_token_ids") or []
        for tid in (199999, 200012):
            if tid not in existing:
                existing.append(tid)
        payload["stop_token_ids"] = existing

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
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function") or {}
                if "arguments" in fn:
                    fn["arguments"] = runpod_service._normalize_tool_call_arguments(
                        fn["arguments"]
                    )
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

    # Stream content from RunPod. The runpod_service yields three shapes:
    #   - "__STATUS:<json>"  internal queue/progress markers (dropped here)
    #   - "__CHUNK:<json>"   full vLLM SSE chunk dict (with delta.content
    #                        AND/OR delta.tool_calls AND/OR finish_reason)
    #   - "<plain text>"     legacy fallback when vLLM returned non-SSE text
    #
    # vLLM's qwen3_coder parser emits *cumulative* tool-call arguments in
    # every chunk instead of OpenAI-style incremental deltas, and sometimes
    # double-encodes them as JSON strings. To stay robust, we BUFFER tool
    # calls per (choice_index, tool_index), accumulate cumulatively, then
    # emit a single normalized tool_call chunk just before finish_reason.
    # Content is still streamed in real time.
    finish_emitted = False
    tool_buffers: dict[int, dict[int, dict]] = {}  # ci -> {ti -> {name,id,type,args}}

    def _flush_tool_calls(ci: int) -> ChatCompletionChunk | None:
        if ci not in tool_buffers or not tool_buffers[ci]:
            return None
        tcs_out = []
        for ti in sorted(tool_buffers[ci].keys()):
            buf = tool_buffers[ci][ti]
            args = buf.get("args", "")
            args = runpod_service._normalize_tool_call_arguments(args)
            tcs_out.append({
                "index": ti,
                "id": buf.get("id"),
                "type": buf.get("type", "function"),
                "function": {
                    "name": buf.get("name") or "",
                    "arguments": args,
                },
            })
        return ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[StreamChoice(
                index=ci,
                delta=DeltaMessage(tool_calls=tcs_out),
                finish_reason=None,
            )],
        )

    async for raw in runpod_service.stream_inference(model.runpod_endpoint_id, payload):
        if not raw:
            continue
        if raw.startswith("__STATUS:"):
            continue

        if raw.startswith("__CHUNK:"):
            try:
                src = json.loads(raw[len("__CHUNK:"):])
            except (ValueError, json.JSONDecodeError):
                continue
            src_choices = src.get("choices") or []
            if not src_choices:
                continue

            for sc in src_choices:
                ci = sc.get("index", 0)
                delta_in = sc.get("delta") or {}
                fr = sc.get("finish_reason")
                tool_calls_in = delta_in.get("tool_calls")
                content = delta_in.get("content")
                role = delta_in.get("role")

                # Buffer tool_calls without forwarding yet
                if tool_calls_in:
                    tool_buffers.setdefault(ci, {})
                    for tc in tool_calls_in:
                        ti = tc.get("index", 0)
                        buf = tool_buffers[ci].setdefault(ti, {"name": "", "id": "", "type": "function", "args": ""})
                        if tc.get("id"):
                            buf["id"] = tc["id"]
                        if tc.get("type"):
                            buf["type"] = tc["type"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            buf["name"] = fn["name"]
                        new_args = fn.get("arguments")
                        if new_args is not None:
                            prev = buf["args"]
                            if new_args.startswith(prev):
                                # Cumulative form
                                buf["args"] = new_args
                            else:
                                # Incremental form (or unrelated chunk)
                                buf["args"] = prev + new_args

                # Forward role/content immediately as their own chunk (preserves real-time UX)
                if role is not None or content is not None:
                    yield "data: " + ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[StreamChoice(
                            index=ci,
                            delta=DeltaMessage(role=role, content=content),
                            finish_reason=None,
                        )],
                    ).model_dump_json() + "\n\n"

                if fr is not None:
                    # Flush buffered tool_calls in one normalized chunk first
                    flush = _flush_tool_calls(ci)
                    if flush is not None:
                        yield "data: " + flush.model_dump_json() + "\n\n"
                        if fr == "stop":
                            fr = "tool_calls"
                        tool_buffers[ci] = {}
                    finish_emitted = True
                    yield "data: " + ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[StreamChoice(
                            index=ci,
                            delta=DeltaMessage(),
                            finish_reason=fr,
                        )],
                    ).model_dump_json() + "\n\n"
            continue

        # Legacy text-only path (no structured chunk available)
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[StreamChoice(index=0, delta=DeltaMessage(content=raw), finish_reason=None)],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"

    # If runpod stream ended without an explicit finish, flush any buffered
    # tool_calls and emit the canonical finish_reason.
    if not finish_emitted:
        for ci in list(tool_buffers.keys()):
            flush = _flush_tool_calls(ci)
            if flush is not None:
                yield "data: " + flush.model_dump_json() + "\n\n"
                tool_buffers[ci] = {}

    if not finish_emitted:
        finish_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[StreamChoice(index=0, delta=DeltaMessage(), finish_reason="stop")],
        )
        yield f"data: {finish_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
