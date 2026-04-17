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
            "env": [
                {"key": "MODEL_NAME", "value": hf_repo},
                {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
                {"key": "GENERATION_CONFIG", "value": "vllm"},
                {"key": "ENABLE_AUTO_TOOL_CHOICE", "value": "true"},
                # Qwen3-Coder is trained on the
                # `<function=name><parameter=...>...</parameter></function>` XML
                # dialect — only vLLM's `qwen3_coder` parser handles it. The
                # `qwen3_xml` parser (generic `<tool_call>{...}` wrapper) silently
                # misses tool calls under long agent prompts (opencode #1809,
                # vLLM/opencode #16488). Backend's deploy_profile_service uses
                # the same mapping; keep these two paths consistent.
                {"key": "TOOL_CALL_PARSER", "value": resolve_tool_parser({"id": hf_repo})},
                {"key": "ENABLE_PREFIX_CACHING", "value": "true"},
                {"key": "ENABLE_CHUNKED_PREFILL", "value": "true"},
            ],
        }
    }

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
