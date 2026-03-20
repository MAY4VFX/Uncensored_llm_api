import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RUNPOD_MANAGE_URL = "https://api.runpod.io/v2"
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


def _graphql_url() -> str:
    """GraphQL URL with api_key as query param (RunPod requires this for auth)."""
    return f"{RUNPOD_GRAPHQL_URL}?api_key={settings.runpod_api_key}"


def _graphql_headers() -> dict:
    return {"Content-Type": "application/json"}


# GPUs ordered by VRAM (ascending). Each entry: (our_name, vram_gb, [runpod_ids])
# Excluded: A40/L40S (AMPERE_48, ADA_48_PRO) — always Low Supply, causes throttling
GPU_TIERS = [
    ("RTX_4000_Ada_20GB", 20, ["AMPERE_16"]),
    ("RTX_A5000_24GB", 24, ["ADA_24", "AMPERE_24"]),
    ("A100_80GB", 80, ["AMPERE_80", "ADA_80_PRO"]),
    ("H100_80GB", 80, ["HOPPER_80"]),
    ("H200_141GB", 141, ["HOPPER_141"]),
]

# Legacy map for existing endpoints that already have a gpu_type stored
GPU_ID_MAP = {name: ",".join(ids) for name, _, ids in GPU_TIERS}


def _build_gpu_ids(gpu_type: str) -> str:
    """Build a comma-separated gpuIds string: the requested GPU + all more powerful ones as fallback."""
    # Try matching by our canonical name first
    found = False
    all_ids = []
    for name, _, ids in GPU_TIERS:
        if name == gpu_type:
            found = True
        if found:
            all_ids.extend(ids)
    if all_ids:
        return ",".join(all_ids)

    # Legacy: gpu_type may contain RunPod IDs directly (from old scout data)
    # Find the tier that contains any of these IDs, then build chain from there
    gpu_type_ids = set(gpu_type.replace(" ", "").split(","))
    for i, (name, _, ids) in enumerate(GPU_TIERS):
        if gpu_type_ids & set(ids):
            all_ids = []
            for _, _, tier_ids in GPU_TIERS[i:]:
                all_ids.extend(tier_ids)
            return ",".join(all_ids)

    # Fallback: include everything from A100 and up
    all_ids = []
    for name, _, ids in GPU_TIERS:
        if name in ("A100_40GB", "A100_80GB", "H100_80GB", "H200_141GB"):
            all_ids.extend(ids)
    return ",".join(all_ids)

# RunPod serverless GPU hourly cost (USD per GPU) — used for keep warm pricing
GPU_HOURLY_COST = {
    "RTX_4000_Ada_20GB": 0.58,
    "RTX_A4500_20GB": 0.58,
    "RTX_A5000_24GB": 0.74,
    "A100_40GB": 1.12,
    "A100_80GB": 1.58,
    "H100_80GB": 2.49,
    "H200_141GB": 3.29,
}


VLLM_IMAGE_REPO = "runpod/worker-v1-vllm"
VLLM_IMAGE_FALLBACK = f"{VLLM_IMAGE_REPO}:v2.14.0"

_cached_latest_tag: str | None = None


async def _get_latest_vllm_image() -> str:
    """Fetch the latest stable tag from Docker Hub for the vLLM worker image."""
    global _cached_latest_tag
    if _cached_latest_tag:
        logger.info(f"Using cached vLLM image tag: {_cached_latest_tag}")
        return f"{VLLM_IMAGE_REPO}:{_cached_latest_tag}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://hub.docker.com/v2/repositories/{VLLM_IMAGE_REPO}/tags",
                params={"page_size": 50, "ordering": "last_updated"},
            )
            resp.raise_for_status()
            for tag in resp.json().get("results", []):
                name = tag.get("name", "")
                # Only match stable version tags like v2.14.0
                if name.startswith("v") and name[1:2].isdigit() and "dev" not in name:
                    _cached_latest_tag = name
                    logger.info(f"Resolved latest vLLM image: {VLLM_IMAGE_REPO}:{name}")
                    return f"{VLLM_IMAGE_REPO}:{name}"
    except Exception as e:
        logger.warning(f"Failed to fetch latest vLLM tag from Docker Hub: {e}")
    logger.info(f"Using fallback vLLM image: {VLLM_IMAGE_FALLBACK}")
    return VLLM_IMAGE_FALLBACK


async def _resolve_gguf(hf_repo: str) -> tuple[str, str]:
    """Resolve a GGUF HuggingFace repo to a direct .gguf file URL and base tokenizer.

    Returns (gguf_file_url, tokenizer_repo).
    Picks Q4_K_M if available, otherwise the first .gguf file found.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://huggingface.co/api/models/{hf_repo}")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch GGUF repo metadata: {e}")
        return hf_repo, ""

    # Find best .gguf file (prefer Q4_K_M)
    siblings = data.get("siblings", [])
    gguf_files = [s["rfilename"] for s in siblings if s.get("rfilename", "").endswith(".gguf") and not s["rfilename"].startswith("mmproj")]
    if not gguf_files:
        logger.warning(f"No .gguf files found in {hf_repo}")
        return hf_repo, ""

    # Priority: Q4_K_M > Q4_K_S > Q8_0 > first available
    chosen = gguf_files[0]
    for preferred in ["Q4_K_M", "Q4_K_S", "Q8_0"]:
        match = [f for f in gguf_files if preferred in f]
        if match:
            chosen = match[0]
            break

    # Direct download URL — vLLM accepts local paths or URLs
    gguf_url = f"https://huggingface.co/{hf_repo}/resolve/main/{chosen}"

    # Resolve base model tokenizer from cardData or tags
    tokenizer = ""
    card_data = data.get("cardData", {})
    base_model = card_data.get("base_model", "")
    if isinstance(base_model, list):
        base_model = base_model[0] if base_model else ""
    if base_model:
        tokenizer = base_model

    if not tokenizer:
        # Try to find base_model from tags
        for tag in data.get("tags", []):
            if tag.startswith("base_model:") and "quantized" not in tag:
                tokenizer = tag.split(":", 1)[1]
                break

    logger.info(f"GGUF resolved: {chosen} from {hf_repo}, tokenizer={tokenizer}")
    return gguf_url, tokenizer


async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "",
    model_name: str = "",
    max_workers: int = 1,
    idle_timeout: int = 30,
    params_b: float = 0,
    max_model_len: int = 4096,
    gpu_count: int = 1,
) -> dict:
    """Create a RunPod template + Serverless Endpoint via GraphQL API."""
    if not docker_image:
        docker_image = await _get_latest_vllm_image()

    logger.info(f"Creating endpoint: name={name} model={model_name} gpu={gpu_type} gpu_count={gpu_count} image={docker_image} params_b={params_b}")

    # GGUF models: resolve to direct .gguf file URL + set tokenizer from base model
    is_gguf = "-gguf" in model_name.lower() or "-GGUF" in model_name
    tokenizer = ""
    if is_gguf:
        gguf_file, tokenizer = await _resolve_gguf(model_name)
        logger.info(f"GGUF model resolved: file={gguf_file} tokenizer={tokenizer}")
        model_name = gguf_file

    env_vars = [
        {"key": "MODEL_NAME", "value": model_name},
        {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
        {"key": "TRUST_REMOTE_CODE", "value": "1"},
    ]
    if tokenizer:
        env_vars.append({"key": "TOKENIZER_NAME", "value": tokenizer})
    if settings.hf_token:
        env_vars.append({"key": "HF_TOKEN", "value": settings.hf_token})

    # Scale container disk based on model size (model weights + runtime overhead)
    # FP16: ~2 bytes/param, Q4: ~0.5 bytes/param, plus vLLM/CUDA overhead (~15GB)
    if params_b >= 65:
        container_disk = 200
    elif params_b >= 30:
        container_disk = 120
    elif params_b >= 20:
        container_disk = 100
    elif params_b >= 10:
        container_disk = 80
    else:
        container_disk = 50

    logger.info(f"Container disk: {container_disk}GB for {params_b}B model")

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: Create template (inline mutation — RunPod doesn't support parameterized variables)
        tmpl_name = f"tpl-{name}-{uuid.uuid4().hex[:6]}"[:50]
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
            f' volumeInGb: 0,'
            f' isServerless: true,'
            f' env: [{env_str}]'
            f' }}) {{ id name }} }}'
        )
        tmpl_resp = await client.post(
            _graphql_url(),
            headers=_graphql_headers(),
            json={"query": tmpl_query},
        )
        tmpl_resp.raise_for_status()
        tmpl_data = tmpl_resp.json()
        if "errors" in tmpl_data:
            logger.error(f"Template creation failed: {tmpl_data['errors']}")
            raise RuntimeError(f"Template creation failed: {tmpl_data['errors']}")
        template_id = tmpl_data["data"]["saveTemplate"]["id"]
        logger.info(f"Template created: {template_id} ({tmpl_name})")

        # Step 2: Create endpoint with template
        runpod_gpu = _build_gpu_ids(gpu_type)
        logger.info(f"GPU chain: {runpod_gpu} (base: {gpu_type})")
        ep_name = name[:50]
        gpu_count_field = f' gpuCount: {gpu_count},' if gpu_count > 1 else ''
        ep_query = (
            f'mutation {{ saveEndpoint(input: {{'
            f' name: "{ep_name}",'
            f' templateId: "{template_id}",'
            f' gpuIds: "{runpod_gpu}",'
            f'{gpu_count_field}'
            f' workersMin: 0,'
            f' workersMax: {max_workers},'
            f' idleTimeout: {idle_timeout},'
            f' scalerType: "QUEUE_DELAY",'
            f' scalerValue: 3'
            f' }}) {{ id name gpuIds templateId }} }}'
        )
        ep_resp = await client.post(
            _graphql_url(),
            headers=_graphql_headers(),
            json={"query": ep_query},
        )
        ep_resp.raise_for_status()
        ep_data = ep_resp.json()
        if "errors" in ep_data:
            logger.error(f"Endpoint creation failed: {ep_data['errors']}")
            raise RuntimeError(f"Endpoint creation failed: {ep_data['errors']}")
        ep_info = ep_data.get("data", {}).get("saveEndpoint", {})
        logger.info(f"Endpoint created: id={ep_info.get('id')} name={ep_info.get('name')} gpus={ep_info.get('gpuIds')}")
        return ep_data


async def _get_endpoint_config(client: httpx.AsyncClient, endpoint_id: str) -> dict:
    """Fetch current endpoint config to preserve fields in saveEndpoint mutations."""
    query = 'query { myself { endpoints { id name gpuIds gpuCount workersMin workersMax idleTimeout } } }'
    resp = await client.post(_graphql_url(), headers=_graphql_headers(), json={"query": query})
    resp.raise_for_status()
    data = resp.json()
    endpoints = data.get("data", {}).get("myself", {}).get("endpoints", [])
    for ep in endpoints:
        if ep.get("id") == endpoint_id:
            return ep
    return {"name": endpoint_id, "gpuIds": "AMPERE_48", "gpuCount": 1, "workersMin": 0, "workersMax": 1, "idleTimeout": 30}


async def update_endpoint_idle_timeout(endpoint_id: str, idle_timeout: int) -> None:
    """Update idleTimeout of an existing RunPod Serverless Endpoint."""
    async with httpx.AsyncClient(timeout=30) as client:
        ep = await _get_endpoint_config(client, endpoint_id)
        gpu_count_field = f' gpuCount: {ep["gpuCount"]},' if ep.get("gpuCount", 1) > 1 else ''
        mutation = (
            f'mutation {{ saveEndpoint(input: {{'
            f' id: "{endpoint_id}",'
            f' name: "{ep["name"]}",'
            f' gpuIds: "{ep["gpuIds"]}",'
            f'{gpu_count_field}'
            f' workersMin: {ep.get("workersMin", 0)},'
            f' workersMax: {ep.get("workersMax", 1)},'
            f' idleTimeout: {idle_timeout}'
            f' }}) {{ id idleTimeout }} }}'
        )
        resp = await client.post(
            _graphql_url(),
            headers=_graphql_headers(),
            json={"query": mutation},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Endpoint update failed: {data['errors']}")


async def update_endpoint_workers_min(endpoint_id: str, workers_min: int) -> None:
    """Update workersMin of an existing RunPod Serverless Endpoint."""
    async with httpx.AsyncClient(timeout=30) as client:
        ep = await _get_endpoint_config(client, endpoint_id)
        workers_max = max(ep.get("workersMax", 1), workers_min)

        gpu_count_field = f' gpuCount: {ep["gpuCount"]},' if ep.get("gpuCount", 1) > 1 else ''
        mutation = (
            f'mutation {{ saveEndpoint(input: {{'
            f' id: "{endpoint_id}",'
            f' name: "{ep["name"]}",'
            f' gpuIds: "{ep["gpuIds"]}",'
            f'{gpu_count_field}'
            f' workersMin: {workers_min},'
            f' workersMax: {workers_max},'
            f' idleTimeout: {ep.get("idleTimeout", 30)}'
            f' }}) {{ id workersMin workersMax }} }}'
        )
        resp = await client.post(
            _graphql_url(),
            headers=_graphql_headers(),
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
            _graphql_url(),
            headers=_graphql_headers(),
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
        workers_idle = workers.get("idle", 0)
        workers_running = workers.get("running", 0)
        initializing = workers.get("initializing", 0)
        throttled = workers.get("throttled", 0)

        # RunPod "idle" means container exists but may need model reload (cold start).
        # Only "running" workers are truly warm and respond instantly.
        if workers_running > 0:
            return {"ready": True, "workers_ready": workers_running, "initializing": initializing, "throttled": throttled, "status": "ready", "estimated_wait": 0}
        elif initializing > 0:
            return {"ready": False, "workers_ready": 0, "initializing": initializing, "throttled": throttled, "status": "warming_up", "estimated_wait": 120}
        elif workers_idle > 0:
            # Idle workers exist but need model loading — faster than full cold start
            return {"ready": False, "workers_ready": 0, "initializing": initializing, "throttled": throttled, "status": "idle", "estimated_wait": 60}
        elif throttled > 0:
            return {"ready": False, "workers_ready": 0, "initializing": 0, "throttled": throttled, "status": "throttled", "estimated_wait": 300}
        else:
            return {"ready": False, "workers_ready": 0, "initializing": 0, "throttled": 0, "status": "cold", "estimated_wait": 180}
    except Exception:
        # On error, assume cold — don't mislead user with "ready"
        return {"ready": False, "workers_ready": 0, "initializing": 0, "throttled": 0, "status": "unknown", "estimated_wait": 60}


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
