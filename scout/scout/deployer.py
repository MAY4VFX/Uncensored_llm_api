"""Auto-deploy models to RunPod Serverless."""

import logging

import httpx

from scout.config import settings

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
            "workersMin": 0,
            "workersMax": max_workers,
            "idleTimeout": idle_timeout,
            "scalerType": "QUEUE_DELAY",
            "scalerValue": 3,
            "dockerImage": "runpod/worker-vllm:stable-cuda12.1.0",
            "env": [
                {"key": "MODEL_NAME", "value": hf_repo},
                {"key": "MAX_MODEL_LEN", "value": "4096"},
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
