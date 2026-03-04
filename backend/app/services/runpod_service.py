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


GPU_ID_MAP = {
    "RTX_4000_Ada_20GB": "ADA_24",
    "RTX_A4500_20GB": "ADA_24",
    "RTX_A5000_24GB": "AMPERE_24",
    "A100_40GB": "AMPERE_48",
    "A100_80GB": "AMPERE_80",
}


async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "runpod/worker-v1-vllm:v2.7.0stable-cuda12.1.0",
    model_name: str = "",
    max_workers: int = 1,
    idle_timeout: int = 30,
) -> dict:
    """Create a RunPod template + Serverless Endpoint via GraphQL API."""
    env_vars = [
        {"key": "MODEL_NAME", "value": model_name},
        {"key": "MAX_MODEL_LEN", "value": "4096"},
        {"key": "TRUST_REMOTE_CODE", "value": "1"},
    ]
    if settings.hf_token:
        env_vars.append({"key": "HF_TOKEN", "value": settings.hf_token})

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Create template
        tmpl_mutation = """
        mutation saveTemplate($input: TemplateInput!) {
            saveTemplate(input: $input) { id name }
        }
        """
        tmpl_vars = {
            "input": {
                "name": f"tpl-{name}"[:50],
                "imageName": docker_image,
                "dockerArgs": "",
                "containerDiskInGb": 40,
                "volumeInGb": 80,
                "env": env_vars,
                "isServerless": True,
            }
        }
        tmpl_resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": tmpl_mutation, "variables": tmpl_vars},
        )
        tmpl_resp.raise_for_status()
        tmpl_data = tmpl_resp.json()
        if "errors" in tmpl_data:
            raise RuntimeError(f"Template creation failed: {tmpl_data['errors']}")
        template_id = tmpl_data["data"]["saveTemplate"]["id"]

        # Step 2: Create endpoint with template
        runpod_gpu = GPU_ID_MAP.get(gpu_type, "AMPERE_48")
        ep_mutation = """
        mutation saveEndpoint($input: EndpointInput!) {
            saveEndpoint(input: $input) { id name gpuIds templateId }
        }
        """
        ep_vars = {
            "input": {
                "name": name[:50],
                "templateId": template_id,
                "gpuIds": runpod_gpu,
                "workersMin": 0,
                "workersMax": max_workers,
                "idleTimeout": idle_timeout,
                "scalerType": "QUEUE_DELAY",
                "scalerValue": 3,
            }
        }
        ep_resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": ep_mutation, "variables": ep_vars},
        )
        ep_resp.raise_for_status()
        ep_data = ep_resp.json()
        if "errors" in ep_data:
            raise RuntimeError(f"Endpoint creation failed: {ep_data['errors']}")
        return ep_data


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
    """Run inference via RunPod /runsync, polling /status if IN_QUEUE."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/runsync"
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(url, headers=_headers(), json={"input": payload})
        resp.raise_for_status()
        data = resp.json()

        # If completed immediately, return
        if data.get("status") == "COMPLETED":
            return data

        # If IN_QUEUE or IN_PROGRESS, poll status until done
        job_id = data.get("id")
        if not job_id:
            return data

        status_url = f"{settings.runpod_base_url}/{endpoint_id}/status/{job_id}"
        for _ in range(120):  # up to ~120 seconds
            await asyncio.sleep(1)
            status_resp = await client.get(status_url, headers=_headers())
            status_data = status_resp.json()
            status = status_data.get("status")
            if status == "COMPLETED":
                return status_data
            elif status == "FAILED":
                raise RuntimeError(f"RunPod job failed: {status_data.get('error')}")

        raise RuntimeError("RunPod inference timed out")


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
