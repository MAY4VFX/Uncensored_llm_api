from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

import modal


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _build_image() -> modal.Image:
    runtime_image = _get_env("MODAL_RUNTIME_IMAGE") or "vllm/vllm-openai:v0.19.1"
    return modal.Image.from_registry(
        runtime_image,
        setup_dockerfile_commands=[
            "ENV PYTHONUNBUFFERED=1",
            "RUN ln -sf $(which python3) /usr/local/bin/python || true",
        ],
    ).entrypoint([])


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


def _server_command() -> list[str]:
    command = [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--model",
        MODEL_NAME,
        "--max-model-len",
        MAX_MODEL_LEN,
        "--served-model-name",
        MODEL_NAME,
    ]
    if TOOL_PARSER and TOOL_PARSER != "none":
        command.extend(["--tool-call-parser", TOOL_PARSER, "--enable-auto-tool-choice"])
    if REASONING_PARSER:
        command.extend(["--reasoning-parser", REASONING_PARSER])
    if GPU_MEMORY_UTILIZATION:
        command.extend(["--gpu-memory-utilization", GPU_MEMORY_UTILIZATION])
    if ENFORCE_EAGER:
        command.append("--enforce-eager")
    if GENERATION_CONFIG:
        command.extend(["--generation-config", GENERATION_CONFIG])
    for key, value in RUNTIME_ARGS_DICT.items():
        flag = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                command.append(flag)
        else:
            command.extend([flag, str(value)])
    return command


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
@modal.web_server(8000, startup_timeout=STARTUP_TIMEOUT)
def openai_api():
    env = os.environ.copy()
    env["HF_HOME"] = "/cache/huggingface"
    env["TRANSFORMERS_CACHE"] = "/cache/huggingface"
    model_name = env.get("MODAL_MODEL_NAME") or MODEL_NAME
    if not model_name:
        raise RuntimeError("MODAL_MODEL_NAME is not set in container env")
    command = _server_command_with(env)
    subprocess.Popen(command, env=env)
    time.sleep(1)


def _server_command_with(env: dict) -> list[str]:
    model_name = env.get("MODAL_MODEL_NAME") or MODEL_NAME
    max_model_len = env.get("MODAL_MAX_MODEL_LEN") or MAX_MODEL_LEN
    tool_parser = env.get("MODAL_TOOL_PARSER") or TOOL_PARSER
    reasoning_parser = env.get("MODAL_REASONING_PARSER") or REASONING_PARSER
    gpu_mem_util = env.get("MODAL_GPU_MEMORY_UTILIZATION") or GPU_MEMORY_UTILIZATION
    default_temp = env.get("MODAL_DEFAULT_TEMPERATURE") or DEFAULT_TEMPERATURE
    enforce_eager = (env.get("MODAL_ENFORCE_EAGER", "false").lower() == "true") or ENFORCE_EAGER
    generation_config = env.get("MODAL_GENERATION_CONFIG_MODE") or GENERATION_CONFIG
    runtime_args = json.loads(env.get("MODAL_RUNTIME_ARGS_JSON") or "{}") or RUNTIME_ARGS_DICT

    command = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--host", "0.0.0.0", "--port", "8000",
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
