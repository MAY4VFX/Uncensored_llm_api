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
    "RTX_4000_Ada_20GB": "AMPERE_16",
    "RTX_A4500_20GB": "AMPERE_16",
    "RTX_A5000_24GB": "ADA_24,AMPERE_24",
    "A100_40GB": "AMPERE_48,ADA_48_PRO",
    "A100_80GB": "AMPERE_80,ADA_80_PRO,HOPPER_141",
}


async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "runpod/worker-v1-vllm:v2.7.0stable-cuda12.1.0",
    model_name: str = "",
    max_workers: int = 1,
    idle_timeout: int = 30,
    params_b: float = 0,
    max_model_len: int = 4096,
) -> dict:
    """Create a RunPod template + Serverless Endpoint via GraphQL API."""
    env_vars = [
        {"key": "MODEL_NAME", "value": model_name},
        {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
        {"key": "TRUST_REMOTE_CODE", "value": "1"},
    ]
    if settings.hf_token:
        env_vars.append({"key": "HF_TOKEN", "value": settings.hf_token})

    # Scale disk size based on model parameters (fp16: ~2 bytes/param + overhead)
    if params_b >= 20:
        container_disk = 80
        volume_gb = 120
    elif params_b >= 10:
        container_disk = 60
        volume_gb = 100
    else:
        container_disk = 40
        volume_gb = 80

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Create template (inline mutation — RunPod doesn't support parameterized variables)
        tmpl_name = f"tpl-{name}"[:50]
        env_str = ", ".join(
            f'{{key: "{e["key"]}", value: "{e["value"]}"}}'
            for e in env_vars
        )
        tmpl_query = (
            f'mutation {{ saveTemplate(input: {{'
            f' name: "{tmpl_name}",'
            f' imageName: "{docker_image}",'
            f' dockerArgs: "",'
            f' containerDiskInGb: {container_disk},'
            f' volumeInGb: {volume_gb},'
            f' isServerless: true,'
            f' env: [{env_str}]'
            f' }}) {{ id name }} }}'
        )
        tmpl_resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": tmpl_query},
        )
        tmpl_resp.raise_for_status()
        tmpl_data = tmpl_resp.json()
        if "errors" in tmpl_data:
            raise RuntimeError(f"Template creation failed: {tmpl_data['errors']}")
        template_id = tmpl_data["data"]["saveTemplate"]["id"]

        # Step 2: Create endpoint with template
        runpod_gpu = GPU_ID_MAP.get(gpu_type, "AMPERE_48")
        ep_name = name[:50]
        ep_query = (
            f'mutation {{ saveEndpoint(input: {{'
            f' name: "{ep_name}",'
            f' templateId: "{template_id}",'
            f' gpuIds: "{runpod_gpu}",'
            f' workersMin: 0,'
            f' workersMax: {max_workers},'
            f' idleTimeout: {idle_timeout},'
            f' scalerType: "QUEUE_DELAY",'
            f' scalerValue: 3'
            f' }}) {{ id name gpuIds templateId }} }}'
        )
        ep_resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": ep_query},
        )
        ep_resp.raise_for_status()
        ep_data = ep_resp.json()
        if "errors" in ep_data:
            raise RuntimeError(f"Endpoint creation failed: {ep_data['errors']}")
        return ep_data


async def update_endpoint_idle_timeout(endpoint_id: str, idle_timeout: int) -> None:
    """Update idleTimeout of an existing RunPod Serverless Endpoint."""
    mutation = (
        f'mutation {{ saveEndpoint(input: {{'
        f' id: "{endpoint_id}",'
        f' idleTimeout: {idle_timeout}'
        f' }}) {{ id idleTimeout }} }}'
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": mutation},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Endpoint update failed: {data['errors']}")


async def update_endpoint_workers_min(endpoint_id: str, workers_min: int) -> None:
    """Update workersMin of an existing RunPod Serverless Endpoint."""
    mutation = (
        f'mutation {{ saveEndpoint(input: {{'
        f' id: "{endpoint_id}",'
        f' workersMin: {workers_min}'
        f' }}) {{ id workersMin }} }}'
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RUNPOD_GRAPHQL_URL,
            headers=_headers(),
            json={"query": mutation},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Endpoint update failed: {data['errors']}")


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


async def check_worker_status(endpoint_id: str) -> dict:
    """Check worker readiness. Returns {ready: bool, workers_ready: int, initializing: int, status: str, estimated_wait: int}.

    RunPod worker states:
    - ready: idle, waiting for jobs
    - running: actively processing a job (still counts as available)
    - initializing: starting up (container + model loading)
    - throttled: queued but no GPU available
    """
    try:
        health = await get_endpoint_health(endpoint_id)
        workers = health.get("workers", {}) if isinstance(health.get("workers"), dict) else {}
        workers_ready = workers.get("ready", 0)
        workers_running = workers.get("running", 0)
        initializing = workers.get("initializing", 0)
        throttled = workers.get("throttled", 0)

        total_active = workers_ready + workers_running
        if total_active > 0:
            return {"ready": True, "workers_ready": total_active, "initializing": initializing, "status": "ready", "estimated_wait": 0}
        elif initializing > 0:
            return {"ready": False, "workers_ready": 0, "initializing": initializing, "status": "warming_up", "estimated_wait": 120}
        elif throttled > 0:
            return {"ready": False, "workers_ready": 0, "initializing": 0, "status": "throttled", "estimated_wait": 300}
        else:
            return {"ready": False, "workers_ready": 0, "initializing": 0, "status": "cold", "estimated_wait": 180}
    except Exception:
        return {"ready": True, "workers_ready": 0, "initializing": 0, "status": "unknown", "estimated_wait": 0}


async def run_inference(endpoint_id: str, payload: dict) -> dict:
    """Run inference via RunPod /runsync, polling /status if IN_QUEUE."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/runsync"
    async with httpx.AsyncClient(timeout=600) as client:
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
        for _ in range(360):  # up to ~360 seconds for cold starts
            await asyncio.sleep(1)
            status_resp = await client.get(status_url, headers=_headers())
            status_data = status_resp.json()
            status = status_data.get("status")
            if status == "COMPLETED":
                return status_data
            elif status == "FAILED":
                raise RuntimeError(f"RunPod job failed: {status_data.get('error')}")

        raise RuntimeError("RunPod inference timed out")


def _parse_sse_content(sse_text: str) -> str | None:
    """Parse vLLM SSE-formatted output and extract concatenated content deltas.

    vLLM with stream=True returns SSE lines like:
        data: {"choices":[{"delta":{"content":"Hello"}}]}
    RunPod passes these as-is in the stream chunk output field.
    Returns concatenated content, or None if not SSE format.
    """
    if "data: " not in sse_text:
        return None
    parts = []
    for line in sse_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            parsed = json.loads(line[6:])
            for choice in parsed.get("choices", []):
                content = choice.get("delta", {}).get("content", "")
                if content:
                    parts.append(content)
        except (json.JSONDecodeError, ValueError):
            continue
    return "".join(parts)


def _extract_text(output) -> str:
    """Extract text content from RunPod output (can be str, dict, or list)."""
    if isinstance(output, str):
        sse_result = _parse_sse_content(output)
        if sse_result is not None:
            return sse_result
        return output
    if isinstance(output, list) and len(output) > 0:
        output = output[0]
    if isinstance(output, dict):
        # vLLM OpenAI-compat response
        choices = output.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            delta = choices[0].get("delta", {})
            return msg.get("content", "") or delta.get("content", "")
        # Raw text field
        return output.get("text", output.get("result", ""))
    return str(output) if output else ""


async def stream_inference(endpoint_id: str, payload: dict) -> AsyncGenerator[str, None]:
    """Run async inference via /run and poll /stream for incremental results.

    Yields text chunks for content, or __STATUS:json markers for queue/progress updates.
    The caller (proxy_service) converts __STATUS markers into SSE status events.
    """
    url = f"{settings.runpod_base_url}/{endpoint_id}/run"

    async with httpx.AsyncClient(timeout=600) as client:
        # Submit job
        resp = await client.post(url, headers=_headers(), json={"input": payload})
        resp.raise_for_status()
        job_id = resp.json()["id"]

        stream_url = f"{settings.runpod_base_url}/{endpoint_id}/stream/{job_id}"
        status_url = f"{settings.runpod_base_url}/{endpoint_id}/status/{job_id}"

        yielded = False
        last_status_yield = 0.0
        queue_start = asyncio.get_event_loop().time()

        while True:
            # Try stream endpoint first
            stream_resp = await client.get(stream_url, headers=_headers())
            if stream_resp.status_code == 200:
                try:
                    data = json.loads(stream_resp.text, strict=False)
                except (json.JSONDecodeError, ValueError):
                    data = {"stream": [], "status": None}

                for chunk in data.get("stream", []):
                    output = chunk.get("output", "")
                    text = _extract_text(output)
                    if text:
                        yield text
                        yielded = True

                status = data.get("status")
                if status == "COMPLETED":
                    return
                if status == "FAILED":
                    raise RuntimeError("RunPod job failed")

                if data.get("stream"):
                    await asyncio.sleep(0.3)
                    continue

            # Check job status when stream is empty (cold start / queue)
            status_resp = await client.get(status_url, headers=_headers())
            try:
                status_data = json.loads(status_resp.text, strict=False)
            except (json.JSONDecodeError, ValueError):
                status_data = {}

            job_status = status_data.get("status")
            if job_status == "COMPLETED":
                if not yielded:
                    output = status_data.get("output", "")
                    text = _extract_text(output)
                    if text:
                        yield text
                return
            elif job_status == "FAILED":
                raise RuntimeError(f"RunPod job failed: {status_data.get('error')}")

            # Yield periodic status updates while waiting in queue
            now = asyncio.get_event_loop().time()
            elapsed = now - queue_start
            if now - last_status_yield >= 5.0:
                last_status_yield = now
                if job_status == "IN_QUEUE":
                    msg = f"Waiting in queue... ({int(elapsed)}s)"
                elif job_status == "IN_PROGRESS":
                    msg = "Generating response..."
                else:
                    msg = f"Status: {job_status} ({int(elapsed)}s)"
                yield f"__STATUS:{json.dumps({'status': job_status, 'message': msg, 'elapsed': int(elapsed)})}"

            await asyncio.sleep(1.0)


async def get_endpoint_health(endpoint_id: str) -> dict:
    """Get health/status of an endpoint."""
    url = f"{settings.runpod_base_url}/{endpoint_id}/health"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()
