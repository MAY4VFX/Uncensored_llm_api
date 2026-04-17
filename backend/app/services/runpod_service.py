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
    # RunPod does not expose a separate H100 80 pool id; use HOPPER_141 for Hopper-tier fallback
    ("H100_80GB", 80, ["HOPPER_141"]),
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
GPT_OSS_IMAGE = "vllm/vllm-openai:v0.11.2"

_cached_latest_tag: str | None = None


def _build_gpt_oss_docker_args(
    model_name: str,
    max_model_len: int,
    tool_parser: str | None,
    runtime_args: dict | None,
) -> str:
    runtime_args = runtime_args or {}
    tensor_parallel_size = runtime_args.get("tensor_parallel_size", 1)
    max_num_batched_tokens = runtime_args.get("max_num_batched_tokens", 1024)
    parser = tool_parser or "openai"

    return " ".join(
        [
            f"--model {model_name}",
            "--host 0.0.0.0",
            "--port 8000",
            f"--max-model-len {max_model_len}",
            f"--tool-call-parser {parser}",
            "--enable-auto-tool-choice",
            f"--tensor-parallel-size {tensor_parallel_size}",
            f"--max-num-batched-tokens {max_num_batched_tokens}",
        ]
    )


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


async def _resolve_gguf(hf_repo: str) -> dict:
    """Resolve a GGUF HuggingFace repo to deployment config.

    Returns dict with keys:
    - gguf_file: filename of chosen .gguf file
    - base_model: HF repo of base model (for tokenizer + config)
    - has_config: whether the GGUF repo has its own config.json
    """
    result = {"gguf_file": "", "base_model": "", "has_config": False}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://huggingface.co/api/models/{hf_repo}")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch GGUF repo metadata: {e}")
        return result

    # Find best .gguf file (prefer Q4_K_M > Q4_K_S > Q8_0)
    siblings = data.get("siblings", [])
    filenames = [s["rfilename"] for s in siblings]
    gguf_files = [f for f in filenames if f.endswith(".gguf") and not f.startswith("mmproj")]
    if not gguf_files:
        logger.warning(f"No .gguf files found in {hf_repo}")
        return result

    chosen = gguf_files[0]
    for preferred in ["Q4_K_M", "Q4_K_S", "Q8_0"]:
        match = [f for f in gguf_files if preferred in f]
        if match:
            chosen = match[0]
            break
    result["gguf_file"] = chosen

    # Check if repo has config.json
    result["has_config"] = "config.json" in filenames

    # Resolve base model from cardData or tags
    card_data = data.get("cardData") or {}
    base_model = card_data.get("base_model", "")
    if isinstance(base_model, list):
        base_model = base_model[0] if base_model else ""
    if not base_model:
        for tag in data.get("tags", []):
            if tag.startswith("base_model:") and "quantized" not in tag:
                base_model = tag.split(":", 1)[1]
                break
    result["base_model"] = base_model

    logger.info(f"GGUF resolved: file={chosen} base={base_model} has_config={result['has_config']} from {hf_repo}")
    return result


RUNPOD_MAX_ENDPOINTS = 5  # RunPod account quota


async def _ensure_endpoint_quota(db) -> None:
    """If at endpoint quota, remove the least-used endpoint to make room.

    Sets the freed model to 'inactive' in the database.
    """
    from app.models import LlmModel

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _graphql_url(), headers=_graphql_headers(),
            json={"query": "{ myself { endpoints { id name } } }"},
        )
        resp.raise_for_status()
        endpoints = resp.json().get("data", {}).get("myself", {}).get("endpoints", [])

    if len(endpoints) < RUNPOD_MAX_ENDPOINTS:
        return  # quota ok

    logger.warning(f"Endpoint quota reached ({len(endpoints)}/{RUNPOD_MAX_ENDPOINTS}), freeing one slot")

    # Find which models own these endpoints
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(LlmModel).where(LlmModel.runpod_endpoint_id.isnot(None))
    )
    models_with_endpoints = {m.runpod_endpoint_id: m for m in result.scalars().all()}

    # Pick the endpoint to remove: prefer models that are idle (no active workers)
    # For simplicity, remove the first endpoint that isn't currently being deployed
    for ep in reversed(endpoints):  # reversed = oldest first
        ep_id = ep["id"]
        model = models_with_endpoints.get(ep_id)
        if model:
            logger.info(f"Freeing endpoint {ep_id} (model: {model.slug}) to make room")
            try:
                await delete_endpoint(ep_id)
            except Exception:
                logger.warning(f"Failed to delete endpoint {ep_id}, trying next")
                continue
            model.runpod_endpoint_id = None
            model.status = "inactive"
            await db.commit()
            return

    # If no model-linked endpoint found, delete the last one
    ep_id = endpoints[-1]["id"]
    logger.info(f"Freeing unlinked endpoint {ep_id}")
    try:
        await delete_endpoint(ep_id)
    except Exception:
        pass


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
    tool_parser: str | None = None,
    reasoning_parser: str | None = None,
    generation_config_mode: str | None = None,
    default_temperature: float | None = None,
    runtime_args: dict | None = None,
    enforce_eager: bool = False,
    gpu_memory_utilization: float | None = None,
    runpod_init_timeout: int | None = None,
    execution_timeout_ms: int | None = None,
    db=None,
) -> dict:
    """Create a RunPod template + Serverless Endpoint via GraphQL API."""
    if db:
        await _ensure_endpoint_quota(db)
    is_gguf = "-gguf" in model_name.lower() or "-GGUF" in model_name

    if not docker_image:
        if is_gguf:
            docker_image = "may4vfx/worker-llamacpp:latest"  # llama.cpp based worker (native GGUF support)
        else:
            # gpt-oss also runs on runpod/worker-v1-vllm — the bare vllm/vllm-openai
            # image has no RunPod queue handler so jobs would hang forever.
            docker_image = await _get_latest_vllm_image()

    logger.info(f"Creating endpoint: name={name} model={model_name} gpu={gpu_type} gpu_count={gpu_count} image={docker_image} gguf={is_gguf}")

    if is_gguf:
        gguf_info = await _resolve_gguf(model_name)
        logger.info(f"GGUF config: {gguf_info}")
        # For GGUF: use llama.cpp worker with -hf repo:quant format
        # Determine quant type from chosen gguf filename (e.g. "Qwen3.5-27B.Q4_K_M.gguf" -> "Q4_K_M")
        gguf_file = gguf_info.get("gguf_file", "")
        quant_type = ""
        if gguf_file:
            # Extract quant from filename: "Model.Q4_K_M.gguf" -> "Q4_K_M"
            parts = gguf_file.rsplit(".", 2)  # ["Model", "Q4_K_M", "gguf"]
            if len(parts) >= 3:
                quant_type = parts[-2]  # "Q4_K_M"

        llama_args = f"-hf {model_name}:{quant_type} --ctx-size {max_model_len} -ngl 999"
        env_vars = [
            {"key": "LLAMA_SERVER_CMD_ARGS", "value": llama_args},
        ]
    else:
        env_vars = [
            {"key": "MODEL_NAME", "value": model_name},
            {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
            {"key": "TRUST_REMOTE_CODE", "value": "1"},
            {"key": "GENERATION_CONFIG", "value": generation_config_mode or "vllm"},
            # Enable OpenAI-style function/tool calling so clients like
            # OpenClaude, Cline and Cursor can use model-family-specific tool protocols.
            {"key": "ENABLE_AUTO_TOOL_CHOICE", "value": "true"},
            {"key": "TOOL_CALL_PARSER", "value": tool_parser or "hermes"},
            {"key": "ENABLE_PREFIX_CACHING", "value": "true"},
            {"key": "ENABLE_CHUNKED_PREFILL", "value": "true"},
            {"key": "VLLM_LOGGING_LEVEL", "value": "INFO"},
            {"key": "ENABLE_LOG_REQUESTS", "value": "true"},
        ]
        if default_temperature is not None:
            env_vars.append({"key": "DEFAULT_TEMPERATURE", "value": str(default_temperature)})
        if reasoning_parser:
            env_vars.append({"key": "REASONING_PARSER", "value": reasoning_parser})
        if enforce_eager:
            env_vars.append({"key": "ENFORCE_EAGER", "value": "true"})
        if gpu_memory_utilization is not None:
            env_vars.append({"key": "GPU_MEMORY_UTILIZATION", "value": str(gpu_memory_utilization)})
        if runpod_init_timeout is not None:
            # RunPod platform-level timeout: how long the worker has to become
            # ready before being killed. Default is ~7 min, too short for
            # large-model cold starts (gpt-oss-120b needs ~13 min).
            env_vars.append({"key": "RUNPOD_INIT_TIMEOUT", "value": str(runpod_init_timeout)})
        if gpu_count and gpu_count > 1:
            # Keep env-driven tensor parallelism consistent with our explicit
            # gpu_count so worker-v1-vllm picks it up even if auto-detection
            # sees only one visible GPU at import time.
            env_vars.append({"key": "TENSOR_PARALLEL_SIZE", "value": str(gpu_count)})

    if settings.hf_token:
        env_vars.append({"key": "HF_TOKEN", "value": settings.hf_token})

    # Scale container disk based on model size (model weights + runtime overhead)
    # 100B+ reasoning models need extra headroom for downloads, unpacking and runtime cache.
    if params_b >= 100:
        container_disk = 300
    elif params_b >= 65:
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
        tmpl_name = f"tpl-{uuid.uuid4().hex[:12]}"
        env_str = ", ".join(
            f'{{key: "{e["key"]}", value: "{e["value"].replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"}}'
            for e in env_vars
        )
        # runpod/worker-v1-vllm reads all config from env vars and writes its
        # own entrypoint — passing custom dockerArgs would override the
        # entrypoint and make tini try to exec the first token as a command.
        # Leave dockerArgs empty so the worker's own handler runs.
        docker_args = ""
        escaped_docker_args = docker_args.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))
        tmpl_query = (
            f'mutation {{ saveTemplate(input: {{'
            f' name: "{tmpl_name}",'
            f' imageName: "{docker_image}",'
            f' dockerArgs: "{escaped_docker_args}",'
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
        # executionTimeoutMs gates the max runtime of a single job. RunPod's
        # default (~10 min) kills long-loading workers mid-inference too, so
        # for big models we raise it alongside RUNPOD_INIT_TIMEOUT.
        exec_timeout_field = (
            f' executionTimeoutMs: {int(execution_timeout_ms)},' if execution_timeout_ms else ''
        )
        ep_query = (
            f'mutation {{ saveEndpoint(input: {{'
            f' name: "{ep_name}",'
            f' templateId: "{template_id}",'
            f' gpuIds: "{runpod_gpu}",'
            f'{gpu_count_field}'
            f' workersMin: 0,'
            f' workersMax: {max_workers},'
            f' idleTimeout: {idle_timeout},'
            f'{exec_timeout_field}'
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


def _normalize_tool_call_arguments(arguments) -> str:
    """Workaround for the vLLM `qwen3_coder` streaming parser bug (opencode
    issues #1809, #16488): in stream mode it emits `function.arguments` as a
    *JSON-encoded* string, e.g. `"{\\"filePath\\":\\"...\\"}"`, while OpenAI
    spec requires arguments to be a plain JSON-object string like
    `{"filePath":"..."}`.

    If the value parses into a string that itself parses into a JSON object,
    unwrap it. Otherwise return as-is.
    """
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


def _normalize_chunk(chunk: dict) -> dict:
    """Normalize vLLM streaming chunk in place — repair tool_call arguments
    that the qwen3_coder parser returns double-encoded.
    """
    for ch in chunk.get("choices") or []:
        delta = ch.get("delta") or {}
        for tc in delta.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if "arguments" in fn:
                fn["arguments"] = _normalize_tool_call_arguments(fn["arguments"])
        msg = ch.get("message") or {}
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if "arguments" in fn:
                fn["arguments"] = _normalize_tool_call_arguments(fn["arguments"])
    return chunk


def _parse_sse_chunks(sse_text: str) -> list[dict]:
    """Parse vLLM SSE-formatted output and return raw chunk dicts.

    vLLM streaming returns chunks like:
        data: {"choices":[{"delta":{"tool_calls":[...]}, "finish_reason": null}]}
    We need the FULL delta (including tool_calls) so the proxy can forward
    structured tool-call streams to OpenAI-compatible clients (opencode, etc.).
    """
    if not isinstance(sse_text, str) or "data: " not in sse_text:
        return []
    chunks: list[dict] = []
    for line in sse_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            chunks.append(_normalize_chunk(json.loads(line[6:])))
        except (json.JSONDecodeError, ValueError):
            continue
    return chunks


def _extract_chunks(output) -> list[dict]:
    """Return list of raw vLLM chunk dicts from a single RunPod stream item.

    Handles three shapes:
      - str: SSE-formatted text (possibly multiple `data:` lines)
      - dict with `choices[].delta`: a single chunk dict, return as-is
      - dict with `choices[].message`: a non-stream completion, normalized into
        a single chunk dict so streaming and non-streaming paths stay uniform
    """
    if isinstance(output, str):
        return _parse_sse_chunks(output)
    if isinstance(output, list) and len(output) > 0:
        output = output[0]
    if isinstance(output, dict):
        choices = output.get("choices") or []
        if choices and "delta" in choices[0]:
            return [output]
        if choices and "message" in choices[0]:
            normalized = []
            for ch in choices:
                msg = ch.get("message", {})
                delta = {}
                if msg.get("content") is not None:
                    delta["content"] = msg["content"]
                if msg.get("tool_calls"):
                    delta["tool_calls"] = msg["tool_calls"]
                normalized.append({
                    "choices": [{
                        "index": ch.get("index", 0),
                        "delta": delta,
                        "finish_reason": ch.get("finish_reason"),
                    }]
                })
            return normalized
    return []


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
                    chunks_out = _extract_chunks(output)
                    if chunks_out:
                        for c in chunks_out:
                            yield "__CHUNK:" + json.dumps(c)
                            yielded = True
                    else:
                        # Fallback: pure text without OpenAI chunk wrapping
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
                    chunks_out = _extract_chunks(output)
                    if chunks_out:
                        for c in chunks_out:
                            yield "__CHUNK:" + json.dumps(c)
                    else:
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
