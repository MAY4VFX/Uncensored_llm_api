from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
import modal
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


LOCAL_VLLM_PORT = int(_get_env("MODAL_LOCAL_VLLM_PORT", "8000"))
MODEL_FAMILY = _get_env("MODAL_MODEL_FAMILY")
LOCAL_LLAMA_PORT = int(_get_env("MODAL_LOCAL_LLAMA_PORT", "8001"))
LLAMA_SERVER_BINARY = _get_env("MODAL_LLAMA_SERVER_BINARY", "llama-server")
GGUF_FILE = _get_env("MODAL_GGUF_FILE")


def _build_image() -> modal.Image:
    runtime_image = _get_env("MODAL_RUNTIME_IMAGE") or "vllm/vllm-openai:v0.19.1"
    return modal.Image.from_registry(
        runtime_image,
        setup_dockerfile_commands=[
            "ENV PYTHONUNBUFFERED=1",
            "RUN ln -sf $(which python3) /usr/local/bin/python || true",
        ],
    ).pip_install("fastapi", "httpx").entrypoint([])


APP_NAME = _get_env("MODAL_APP_NAME") or "unchained-modal-app"
FUNCTION_NAME = _get_env("MODAL_FUNCTION_NAME") or "openai_api"
MODEL_NAME = _get_env("MODAL_MODEL_NAME")
MAX_MODEL_LEN = _get_env("MODAL_MAX_MODEL_LEN", "4096")
GPU = _get_env("MODAL_GPU", "H100")
TIMEOUT = int(_get_env("MODAL_TIMEOUT_SECONDS", "3600"))
STARTUP_TIMEOUT = int(_get_env("MODAL_STARTUP_TIMEOUT_SECONDS", "1800"))
SCALEDOWN_WINDOW = int(_get_env("MODAL_SCALEDOWN_WINDOW_SECONDS", "300"))
MIN_CONTAINERS = int(_get_env("MODAL_MIN_CONTAINERS", "0"))
MAX_CONTAINERS = int(_get_env("MODAL_MAX_CONTAINERS", "1"))
BUFFER_CONTAINERS = int(_get_env("MODAL_BUFFER_CONTAINERS", "0"))
HF_TOKEN = _get_env("HF_TOKEN")
TOOL_PARSER = _get_env("MODAL_TOOL_PARSER")
REASONING_PARSER = _get_env("MODAL_REASONING_PARSER")
GENERATION_CONFIG = _get_env("MODAL_GENERATION_CONFIG_MODE", "vllm")
DEFAULT_TEMPERATURE = _get_env("MODAL_DEFAULT_TEMPERATURE")
GPU_MEMORY_UTILIZATION = _get_env("MODAL_GPU_MEMORY_UTILIZATION")
ENFORCE_EAGER = _get_env("MODAL_ENFORCE_EAGER", "false").lower() == "true"
VOLUME_NAME = _get_env("MODAL_VOLUME_NAME") or f"{APP_NAME}-weights"
RUNTIME_ARGS = _get_env("MODAL_RUNTIME_ARGS_JSON", "{}")
RUNTIME_ARGS_DICT = json.loads(RUNTIME_ARGS) if RUNTIME_ARGS else {}
ENVIRONMENT_NAME = _get_env("MODAL_ENVIRONMENT", "main")

_TP = int(RUNTIME_ARGS_DICT.get("tensor_parallel_size") or 1)
GPU_SPEC = f"{GPU}:{_TP}" if _TP > 1 else GPU

_RUNTIME_ENV = {
    k: os.environ[k]
    for k in os.environ
    if k.startswith("MODAL_") or k == "HF_TOKEN"
}
image = _build_image().env(_RUNTIME_ENV)
secret = modal.Secret.from_dict(_RUNTIME_ENV) if _RUNTIME_ENV else None
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
app = modal.App(APP_NAME)


def _vllm_server_command_with(env: dict[str, str]) -> list[str]:
    model_name = env.get("MODAL_MODEL_NAME") or MODEL_NAME
    max_model_len = env.get("MODAL_MAX_MODEL_LEN") or MAX_MODEL_LEN
    tool_parser = env.get("MODAL_TOOL_PARSER") or TOOL_PARSER
    reasoning_parser = env.get("MODAL_REASONING_PARSER") or REASONING_PARSER
    gpu_mem_util = env.get("MODAL_GPU_MEMORY_UTILIZATION") or GPU_MEMORY_UTILIZATION
    enforce_eager = (env.get("MODAL_ENFORCE_EAGER", "false").lower() == "true") or ENFORCE_EAGER
    generation_config = env.get("MODAL_GENERATION_CONFIG_MODE") or GENERATION_CONFIG
    runtime_args = json.loads(env.get("MODAL_RUNTIME_ARGS_JSON") or "{}") or RUNTIME_ARGS_DICT

    command = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--host", "127.0.0.1", "--port", str(LOCAL_VLLM_PORT),
        "--model", model_name,
        "--max-model-len", str(max_model_len),
        "--served-model-name", model_name,
    ]
    if tool_parser and tool_parser != "none":
        command.extend(["--tool-call-parser", tool_parser, "--enable-auto-tool-choice"])
    if reasoning_parser:
        command.extend(["--reasoning-parser", reasoning_parser])
    if gpu_mem_util:
        command.extend(["--gpu-memory-utilization", str(gpu_mem_util)])
    if enforce_eager:
        command.append("--enforce-eager")
    if generation_config:
        command.extend(["--generation-config", generation_config])
    for key, value in runtime_args.items():
        flag = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                command.append(flag)
        else:
            command.extend([flag, str(value)])
    return command


def _llama_server_command_with(env: dict[str, str]) -> list[str]:
    model_name = env.get("MODAL_MODEL_NAME") or MODEL_NAME
    gguf_file = env.get("MODAL_GGUF_FILE") or GGUF_FILE
    max_model_len = env.get("MODAL_MAX_MODEL_LEN") or MAX_MODEL_LEN
    local_port = int(env.get("MODAL_LOCAL_LLAMA_PORT") or LOCAL_LLAMA_PORT)
    binary = env.get("MODAL_LLAMA_SERVER_BINARY") or LLAMA_SERVER_BINARY
    runtime_args = json.loads(env.get("MODAL_RUNTIME_ARGS_JSON") or "{}") or {}

    command = [
        binary,
        "--host", "127.0.0.1",
        "--port", str(local_port),
        "-hf", f"{model_name}:{gguf_file}",
        "--ctx-size", str(max_model_len),
    ]
    ngl = runtime_args.get("ngl")
    if ngl is not None:
        command.extend(["-ngl", str(ngl)])
    if runtime_args.get("jinja"):
        command.append("--jinja")
    return command


def _is_gguf_runtime(env: dict[str, str]) -> bool:
    return (env.get("MODAL_MODEL_FAMILY") or MODEL_FAMILY).strip().lower() == "gguf"


def _normalize_tool_call_arguments(arguments):
    if not isinstance(arguments, str):
        return arguments
    s = arguments.strip()
    if not s.startswith('"') or not s.endswith('"'):
        return arguments
    try:
        inner = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return arguments
    if not isinstance(inner, str):
        return arguments
    inner_stripped = inner.strip()
    if not inner_stripped.startswith(("{", "[")):
        return arguments
    try:
        json.loads(inner)
    except (json.JSONDecodeError, ValueError):
        return arguments
    return inner


def _chunk_payload(
    completion_id: str,
    created: int,
    model_name: str,
    *,
    index: int,
    role: str | None = None,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str | None = None,
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{
            "index": index,
            "delta": {},
            "finish_reason": finish_reason,
        }],
    }
    delta = payload["choices"][0]["delta"]
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


class _OpenAIStreamNormalizer:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self.created = int(time.time())
        self.finish_emitted = False
        self.tool_buffers: dict[int, dict[int, dict[str, Any]]] = {}

    def start(self) -> str:
        return _chunk_payload(
            self.completion_id,
            self.created,
            self.model_name,
            index=0,
            role="assistant",
        )

    def _flush_tool_calls(self, choice_index: int) -> str | None:
        if choice_index not in self.tool_buffers or not self.tool_buffers[choice_index]:
            return None
        out = []
        for tool_index in sorted(self.tool_buffers[choice_index].keys()):
            buf = self.tool_buffers[choice_index][tool_index]
            out.append({
                "index": tool_index,
                "id": buf.get("id") or None,
                "type": buf.get("type", "function"),
                "function": {
                    "name": buf.get("name") or "",
                    "arguments": _normalize_tool_call_arguments(buf.get("args", "")),
                },
            })
        return _chunk_payload(
            self.completion_id,
            self.created,
            self.model_name,
            index=choice_index,
            tool_calls=out,
        )

    def feed(self, upstream_chunk: dict[str, Any]) -> list[str]:
        emitted: list[str] = []
        for choice in upstream_chunk.get("choices") or []:
            choice_index = choice.get("index", 0)
            delta = choice.get("delta") or {}
            finish_reason = choice.get("finish_reason")
            tool_calls = delta.get("tool_calls") or []
            content = delta.get("content")
            role = delta.get("role")

            if tool_calls:
                self.tool_buffers.setdefault(choice_index, {})
                for tool_call in tool_calls:
                    tool_index = tool_call.get("index", 0)
                    buf = self.tool_buffers[choice_index].setdefault(
                        tool_index,
                        {"name": "", "id": "", "type": "function", "args": ""},
                    )
                    if tool_call.get("id"):
                        buf["id"] = tool_call["id"]
                    if tool_call.get("type"):
                        buf["type"] = tool_call["type"]
                    fn = tool_call.get("function") or {}
                    if fn.get("name"):
                        buf["name"] = fn["name"]
                    new_args = fn.get("arguments")
                    if new_args is not None:
                        prev = buf.get("args", "")
                        if isinstance(new_args, str) and new_args.startswith(prev):
                            buf["args"] = new_args
                        else:
                            buf["args"] = prev + str(new_args)

            if role is not None or content is not None:
                emitted.append(
                    _chunk_payload(
                        self.completion_id,
                        self.created,
                        self.model_name,
                        index=choice_index,
                        role=role,
                        content=content,
                    )
                )

            if finish_reason is not None:
                flushed = self._flush_tool_calls(choice_index)
                if flushed is not None:
                    emitted.append(flushed)
                    if finish_reason == "stop":
                        finish_reason = "tool_calls"
                    self.tool_buffers[choice_index] = {}
                self.finish_emitted = True
                emitted.append(
                    _chunk_payload(
                        self.completion_id,
                        self.created,
                        self.model_name,
                        index=choice_index,
                        finish_reason=finish_reason,
                    )
                )
        return emitted

    def finalize(self) -> list[str]:
        emitted: list[str] = []
        if not self.finish_emitted:
            for choice_index in list(self.tool_buffers.keys()):
                flushed = self._flush_tool_calls(choice_index)
                if flushed is not None:
                    emitted.append(flushed)
                    self.tool_buffers[choice_index] = {}
        if not self.finish_emitted:
            emitted.append(
                _chunk_payload(
                    self.completion_id,
                    self.created,
                    self.model_name,
                    index=0,
                    finish_reason="stop",
                )
            )
        emitted.append("data: [DONE]\n\n")
        return emitted


async def _wait_until_ready(
    client: httpx.AsyncClient,
    base_url: str,
    proc: subprocess.Popen[Any],
    runtime_name: str,
) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{runtime_name} process exited early with code {proc.returncode}")
        for path in ("/health", "/v1/models"):
            try:
                response = await client.get(
                    f"{base_url}{path}",
                    timeout=httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=None),
                )
                if response.status_code == 200:
                    return
            except Exception:
                pass
        await asyncio.sleep(1)
    raise RuntimeError(f"{runtime_name} did not become ready within {STARTUP_TIMEOUT}s")


async def _close_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        await asyncio.to_thread(proc.wait, 10)
        return
    except Exception:
        pass
    proc.kill()
    try:
        await asyncio.to_thread(proc.wait, 5)
    except Exception:
        pass


async def _iter_sse_payloads(response: httpx.Response):
    buffer = ""
    async for chunk in response.aiter_text():
        if not chunk:
            continue
        buffer += chunk
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            for line in frame.split("\n"):
                if line.startswith("data: "):
                    yield line[6:].strip()


async def _accumulate_chat_response(response: httpx.Response, model_name: str) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_acc: dict[int, dict[str, Any]] = {}
    finish_reason = "stop"
    response_id = "chatcmpl-modal"
    created = 0
    served_model = model_name
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    chunks_received = 0

    async for data in _iter_sse_payloads(response):
        if data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            continue
        chunks_received += 1
        response_id = obj.get("id") or response_id
        created = obj.get("created") or created
        served_model = obj.get("model") or served_model
        if obj.get("usage"):
            usage = obj["usage"]
        for choice in obj.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning"):
                reasoning_parts.append(delta["reasoning"])
            for tool_call in delta.get("tool_calls") or []:
                index = tool_call.get("index", 0)
                slot = tool_calls_acc.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if tool_call.get("id"):
                    slot["id"] = tool_call["id"]
                if tool_call.get("type"):
                    slot["type"] = tool_call["type"]
                fn = tool_call.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments") is not None:
                    prev = slot["function"]["arguments"]
                    new_args = str(fn["arguments"])
                    if new_args.startswith(prev):
                        slot["function"]["arguments"] = new_args
                    else:
                        slot["function"]["arguments"] = prev + new_args
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    if chunks_received == 0:
        raise RuntimeError("vLLM returned empty stream")

    message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts) or None}
    if reasoning_parts:
        message["reasoning"] = "".join(reasoning_parts)
    if tool_calls_acc:
        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        for tool_call in tool_calls:
            tool_call["function"]["arguments"] = _normalize_tool_call_arguments(tool_call["function"]["arguments"])
        message["tool_calls"] = tool_calls
        message["content"] = None
        if finish_reason == "stop":
            finish_reason = "tool_calls"

    return {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": served_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


def _create_web_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(web_app: FastAPI):
        env = os.environ.copy()
        env["HF_HOME"] = "/cache/huggingface"
        env["TRANSFORMERS_CACHE"] = "/cache/huggingface"
        model_name = env.get("MODAL_MODEL_NAME") or MODEL_NAME
        if not model_name:
            raise RuntimeError("MODAL_MODEL_NAME is not set in container env")

        env["LLAMA_CACHE"] = "/cache/llama"
        if _is_gguf_runtime(env):
            command = _llama_server_command_with(env)
            base_url = f"http://127.0.0.1:{int(env.get('MODAL_LOCAL_LLAMA_PORT') or LOCAL_LLAMA_PORT)}"
            runtime_name = "llama.cpp"
        else:
            command = _vllm_server_command_with(env)
            base_url = f"http://127.0.0.1:{LOCAL_VLLM_PORT}"
            runtime_name = "vLLM"
        proc = subprocess.Popen(command, env=env)
        client = httpx.AsyncClient()
        try:
            await _wait_until_ready(client, base_url, proc, runtime_name)
            web_app.state.proc = proc
            web_app.state.base_url = base_url
            web_app.state.client = client
            web_app.state.runtime_name = runtime_name
            yield
        finally:
            await client.aclose()
            await _close_process(proc)

    web_app = FastAPI(title="Modal OpenAI Proxy", lifespan=lifespan)

    @web_app.get("/health")
    async def health():
        proc = web_app.state.proc
        if proc.poll() is not None:
            return JSONResponse({"status": "error", "message": "upstream process exited"}, status_code=503)
        for path in ("/health", "/v1/models"):
            try:
                response = await web_app.state.client.get(
                    f"{web_app.state.base_url}{path}",
                    timeout=httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=None),
                )
            except Exception:
                continue
            if response.status_code == 200:
                return {"status": "ok"}
        return JSONResponse({"status": "error", "message": "upstream health unavailable"}, status_code=503)

    @web_app.get("/v1/models")
    async def models():
        try:
            response = await web_app.state.client.get(
                f"{web_app.state.base_url}/v1/models",
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=None),
            )
        except Exception as exc:
            return JSONResponse({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, status_code=502)
        try:
            return JSONResponse(response.json(), status_code=response.status_code)
        except ValueError:
            return JSONResponse({"error": response.text[:500]}, status_code=response.status_code)

    @web_app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = dict(await request.json())
        model_name = str(payload.get("model") or MODEL_NAME or "model")
        upstream_url = f"{web_app.state.base_url}/v1/chat/completions"
        timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=None)

        if payload.get("stream"):
            normalizer = _OpenAIStreamNormalizer(model_name)

            async def generate():
                yield normalizer.start()
                try:
                    async with web_app.state.client.stream("POST", upstream_url, json=payload, timeout=timeout) as response:
                        if response.status_code >= 400:
                            message = await response.aread()
                            error_text = message.decode(errors="ignore")[:200]
                            yield f'data: {{"error":"upstream {response.status_code}: {error_text}"}}\n\n'
                            return
                        async for data in _iter_sse_payloads(response):
                            if data == "[DONE]":
                                continue
                            try:
                                src = json.loads(data)
                            except (json.JSONDecodeError, ValueError):
                                continue
                            for out in normalizer.feed(src):
                                yield out
                except Exception as exc:
                    yield f'data: {{"error":"{type(exc).__name__}: {str(exc)[:200]}"}}\n\n'
                    return
                for out in normalizer.finalize():
                    yield out

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
            )

        if web_app.state.runtime_name == "llama.cpp":
            try:
                response = await web_app.state.client.post(upstream_url, json=payload, timeout=timeout)
            except Exception as exc:
                return JSONResponse({"error": f"{type(exc).__name__}: {str(exc)[:500]}"}, status_code=502)
            try:
                return JSONResponse(response.json(), status_code=response.status_code)
            except ValueError:
                return JSONResponse({"error": response.text[:500]}, status_code=response.status_code)

        stream_payload = {**payload, "stream": True}
        try:
            async with web_app.state.client.stream("POST", upstream_url, json=stream_payload, timeout=timeout) as response:
                response.raise_for_status()
                result = await _accumulate_chat_response(response, model_name)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            return JSONResponse({"error": detail}, status_code=exc.response.status_code if exc.response else 502)
        except Exception as exc:
            return JSONResponse({"error": f"{type(exc).__name__}: {str(exc)[:500]}"}, status_code=502)
        return JSONResponse(result)

    return web_app


WEB_APP = _create_web_app()


@app.function(
    image=image,
    gpu=GPU_SPEC,
    timeout=TIMEOUT,
    startup_timeout=STARTUP_TIMEOUT,
    scaledown_window=SCALEDOWN_WINDOW,
    min_containers=MIN_CONTAINERS,
    max_containers=MAX_CONTAINERS,
    buffer_containers=BUFFER_CONTAINERS,
    volumes={"/cache": volume},
    secrets=[secret] if secret else [],
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def openai_api():
    return WEB_APP


def deploy() -> dict[str, object]:
    deployed_app = app.deploy(name=APP_NAME, environment_name=ENVIRONMENT_NAME)
    function = modal.Function.from_name(APP_NAME, FUNCTION_NAME, environment_name=ENVIRONMENT_NAME)
    web_url = function.get_web_url()
    return {
        "app_name": APP_NAME,
        "app_id": getattr(deployed_app, "app_id", None),
        "function_name": FUNCTION_NAME,
        "web_url": web_url,
        "environment": ENVIRONMENT_NAME,
        "volume_name": VOLUME_NAME,
        "gpu": GPU,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["deploy"])
    args = parser.parse_args()
    if args.command == "deploy":
        print(json.dumps(deploy()))
        return
    raise SystemExit(1)


if __name__ == "__main__":
    main()
