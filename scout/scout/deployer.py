"""Auto-deploy models to RunPod Serverless."""

import logging

import httpx

from scout.config import settings
from scout.gpu_selector import resolve_docker_image, resolve_tool_parser

logger = logging.getLogger(__name__)

RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


async def deploy_endpoint(
    name: str,
    gpu_type: str,
    hf_repo: str,
    max_workers: int = 5,
    idle_timeout: int = 30,
    max_model_len: int = 4096,
    gpu_count: int = 1,
) -> str | None:
    """
    Create a RunPod Serverless Endpoint for vLLM.
    Returns endpoint_id or None on failure.
    """
    if not settings.runpod_api_key:
        logger.error("No RunPod API key configured")
        return None

    mutation = """
    mutation createEndpoint($input: EndpointInput!) {
        saveEndpoint(input: $input) {
            id
            name
        }
    }
    """
    is_gpt_oss = "gpt-oss" in hf_repo.lower() or "gpt_oss" in hf_repo.lower()
    env = [
        {"key": "MODEL_NAME", "value": hf_repo},
        {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
        # gpt-oss ships generation_config.json with eos_token_id the parser
        # relies on (OpenAI fork adds <|call|>=200012). GENERATION_CONFIG=auto
        # keeps those in effect; vllm default mode would discard them.
        {"key": "GENERATION_CONFIG", "value": "auto" if is_gpt_oss else "vllm"},
        {"key": "ENABLE_AUTO_TOOL_CHOICE", "value": "true"},
        # Family-specific tool parser (see backend deploy_profile_service /
        # CLAUDE.md: qwen3_coder for XML, openai for gpt-oss harmony, etc.).
        {"key": "TOOL_CALL_PARSER", "value": resolve_tool_parser({"id": hf_repo})},
        {"key": "ENABLE_PREFIX_CACHING", "value": "true"},
        {"key": "ENABLE_CHUNKED_PREFILL", "value": "true"},
    ]
    if is_gpt_oss:
        # Parity with backend/app/services/deploy_profile_service.py gpt_oss
        # profile. Without these the worker either kills itself on CUDA graph
        # compile (no ENFORCE_EAGER), hits RunPod init timeout (no
        # RUNPOD_INIT_TIMEOUT), or parses harmony wrong (no REASONING_PARSER).
        env.extend([
            {"key": "REASONING_PARSER", "value": "openai_gptoss"},
            {"key": "ENFORCE_EAGER", "value": "true"},
            {"key": "GPU_MEMORY_UTILIZATION", "value": "0.90"},
            {"key": "RUNPOD_INIT_TIMEOUT", "value": "1800"},
        ])
        if gpu_count and gpu_count > 1:
            env.append({"key": "TENSOR_PARALLEL_SIZE", "value": str(gpu_count)})

    variables = {
        "input": {
            "name": name,
            "gpuIds": gpu_type,
            "gpuCount": gpu_count,
            "workersMin": 0,
            "workersMax": max_workers,
            "idleTimeout": idle_timeout,
            "scalerType": "QUEUE_DELAY",
            "scalerValue": 3,
            "dockerImage": resolve_docker_image({"id": hf_repo}),
            "env": env,
        }
    }
    if is_gpt_oss:
        # 30-min per-job ceiling so long cold-start + first inference don't
        # trip RunPod's default 10-min executionTimeout.
        variables["input"]["executionTimeoutMs"] = 1_800_000

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                RUNPOD_GRAPHQL_URL,
                headers=_headers(),
                json={"query": mutation, "variables": variables},
            )
            resp.raise_for_status()
            data = resp.json()
            endpoint = data.get("data", {}).get("saveEndpoint", {})
            endpoint_id = endpoint.get("id")

            if endpoint_id:
                logger.info(f"Deployed endpoint {endpoint_id} for {hf_repo}")
                return endpoint_id
            else:
                logger.error(f"Failed to deploy {hf_repo}: {data}")
                return None
    except Exception as e:
        logger.error(f"Error deploying {hf_repo}: {e}")
        return None
