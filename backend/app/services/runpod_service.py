import asyncio
import json
import uuid
from typing import AsyncGenerator

import httpx

from app.config import settings

RUNPOD_MANAGE_URL = "https://api.runpod.io/v2"
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "runpod/worker-vllm:stable-cuda12.1.0",
    model_name: str = "",
    max_workers: int = 5,
    idle_timeout: int = 30,
) -> dict:
    """Create a new RunPod Serverless Endpoint via GraphQL API."""
    env_vars = {"MODEL_NAME": model_name, "MAX_MODEL_LEN": "4096"}
    mutation = """
    mutation createEndpoint($input: EndpointInput!) {
        saveEndpoint(input: $input) {
            id
            name
            gpuIds
            templateId
        }
    }
    """
    variables = {
        "input": {
            "name": name,
            "templateId": None,
            "gpuIds": gpu_type,
            "workersMin": 0,
            "workersMax": max_workers,
            "idleTimeout": idle_timeout,
            "scalerType": "QUEUE_DELAY",
            "scalerValue": 3,
            "dockerImage": docker_image,
            "env": [{"key": k, "value": v} for k, v in env_vars.items()],
        }
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": mutation, "variables": variables},
        )
        resp.raise_for_status()
        return resp.json()


async def delete_endpoint(endpoint_id: str) -> None:
    """Delete a RunPod Serverless Endpoint."""
    mutation = """
    mutation deleteEndpoint($id: String!) {
        deleteEndpoint(id: $id)
    }
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": mutation, "variables": {"id": endpoint_id}},
        )
        resp.raise_for_status()


async def run_inference(endpoint_id: str, payload: dict) -> dict:
    """Run synchronous inference via RunPod /runsync endpoint."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/runsync"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=_headers(), json={"input": payload})
        resp.raise_for_status()
        return resp.json()


async def stream_inference(endpoint_id: str, payload: dict) -> AsyncGenerator[str, None]:
    """Run async inference via /run and poll for results, yielding chunks."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/run"

    async with httpx.AsyncClient(timeout=120) as client:
        # Submit job
        resp = await client.post(url, headers=_headers(), json={"input": payload})
        resp.raise_for_status()
        job_id = resp.json()["id"]

        # Poll for results with streaming
        stream_url = f"{settings.runpod_base_url}/{endpoint_id}/stream/{job_id}"
        status_url = f"{settings.runpod_base_url}/{endpoint_id}/status/{job_id}"

        while True:
            # Try stream endpoint first
            stream_resp = await client.get(stream_url, headers=_headers())
            if stream_resp.status_code == 200:
                data = stream_resp.json()
                for chunk in data.get("stream", []):
                    output = chunk.get("output", "")
                    if output:
                        yield output

                if data.get("status") in ("COMPLETED", "FAILED"):
                    break

            # Fallback: check status
            status_resp = await client.get(status_url, headers=_headers())
            status_data = status_resp.json()
            if status_data.get("status") == "COMPLETED":
                output = status_data.get("output", "")
                if output:
                    yield output if isinstance(output, str) else json.dumps(output)
                break
            elif status_data.get("status") == "FAILED":
                raise RuntimeError(f"RunPod job failed: {status_data.get('error')}")

            await asyncio.sleep(0.5)


async def get_endpoint_health(endpoint_id: str) -> dict:
    """Get health/status of an endpoint."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/health"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()
