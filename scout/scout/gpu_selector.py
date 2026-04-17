"""GPU selection helpers for scout auto-deploy."""

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}

# (primary_gpu_id, vram_gb, cost_per_hour, runpod_pool_ids)
# pool_ids: comma-separated RunPod pool IDs for fallback availability
# Excluded A40/L40S (48GB) because they are typically low-supply on RunPod.
GPU_OPTIONS = [
    ("RTX_4000_Ada_20GB", 8, 0.17, "AMPERE_16"),
    ("RTX_A5000_24GB", 24, 0.28, "ADA_24,AMPERE_24"),
    ("A100_80GB", 80, 1.99, "AMPERE_80,ADA_80_PRO"),
    ("H100_80GB", 80, 2.49, "HOPPER_141"),
    ("H200_141GB", 141, 3.29, "HOPPER_141"),
]

FAMILY_LIMITS = {
    "qwen3_coder": {
        "native_context": 262144,
        "practical_cap": 262144,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "qwen3_coder",
    },
    "qwen3_general": {
        "native_context": 131072,
        "practical_cap": 204800,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "hermes",
    },
    "gpt_oss": {
        "native_context": 128000,
        "practical_cap": 128000,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "openai",
        "docker_image": "vllm/vllm-openai:v0.11.2",
    },
    "fallback": {
        "native_context": 32768,
        "practical_cap": 65536,
        "preferred_gpu": "A100_80GB",
        "tool_parser": "hermes",
    },
}


def _detect_family(model_ref: str | dict) -> str:
    if isinstance(model_ref, dict):
        repo = str(model_ref.get("id") or "").lower()
        tags = [str(tag).lower() for tag in model_ref.get("tags", [])]
        card = model_ref.get("cardData") or {}
        base_model = card.get("base_model") or []
        if isinstance(base_model, str):
            base_model = [base_model]
        base_text = " ".join(
            [
                *(str(item).lower() for item in base_model),
                *(tag.split(":", 1)[1] for tag in tags if tag.startswith("base_model:")),
            ]
        )
    else:
        repo = str(model_ref or "").lower()
        tags = []
        base_text = ""

    if "gpt-oss" in repo or "gpt_oss" in tags or "gpt-oss" in tags or "gpt-oss" in base_text:
        return "gpt_oss"
    if ("qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags) and ("coder" in repo or "coder" in base_text):
        return "qwen3_coder"
    if "qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags:
        return "qwen3_general"
    return "fallback"



def resolve_tool_parser(model_ref: str | dict) -> str:
    family = _detect_family(model_ref)
    return FAMILY_LIMITS[family]["tool_parser"]



def resolve_docker_image(model_ref: str | dict) -> str:
    # All vLLM-backed families use runpod/worker-v1-vllm. The bare
    # vllm/vllm-openai image has no RunPod queue handler, so jobs dispatched
    # via /run would hang in the queue forever (see CLAUDE.md / past
    # gpt-oss-120b debug). Backend and scout deploy paths share this choice.
    return "runpod/worker-v1-vllm:v2.14.0"



def _estimate_safe_context(params_b: float, quant: str, vram_gb: float, family: str) -> int:
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)

    if family == "gpt_oss":
        effective_params_b = min(params_b, 22.0)
        model_vram = effective_params_b * multiplier * 1.15
    else:
        model_vram = params_b * multiplier * 1.15

    free_vram = vram_gb - model_vram
    if free_vram <= 0:
        return 4096

    if family.startswith("qwen3"):
        kv_per_4k = params_b * 0.045
    elif family == "gpt_oss":
        kv_per_4k = params_b * 0.02
    else:
        kv_per_4k = params_b * 0.5

    max_ctx = int((free_vram / max(kv_per_4k, 1.0)) * 4096)
    max_ctx = (max_ctx // 1024) * 1024
    return min(max(max_ctx, 2048), 262144)



def _coerce_minimum_context(family: str, gpu_name: str, computed_context: int) -> int:
    minimums = {
        ("qwen3_coder", "H200_141GB"): 204800,
        ("qwen3_general", "H200_141GB"): 131072,
        ("gpt_oss", "H200_141GB"): 128000,
    }
    return max(computed_context, minimums.get((family, gpu_name), 4096))



def _safe_context_on_gpu(params_b: float, quant: str, gpu_name: str, family: str) -> int:
    for name, vram, _cost_hr, _pool in GPU_OPTIONS:
        if name == gpu_name:
            ctx = _estimate_safe_context(params_b, quant, vram, family)
            return _coerce_minimum_context(family, gpu_name, ctx)
    return 4096



def _select_gpu_for_context(params_b: float, quant: str, desired_context: int, family: str) -> tuple[str, float, int]:
    preferred_gpu = FAMILY_LIMITS[family].get("preferred_gpu")
    if preferred_gpu:
        for gpu_name, _vram, cost_hr, _pool in GPU_OPTIONS:
            if gpu_name != preferred_gpu:
                continue
            safe_ctx = _safe_context_on_gpu(params_b, quant, gpu_name, family)
            if safe_ctx >= desired_context:
                return gpu_name, cost_hr, safe_ctx
            break

    for gpu_name, _vram, cost_hr, _pool in GPU_OPTIONS:
        safe_ctx = _safe_context_on_gpu(params_b, quant, gpu_name, family)
        if safe_ctx >= desired_context:
            return gpu_name, cost_hr, safe_ctx

    gpu_name, _vram, cost_hr, _pool = GPU_OPTIONS[-1]
    return gpu_name, cost_hr, _safe_context_on_gpu(params_b, quant, gpu_name, family)



def resolve_profile(model_ref: str | dict, params_b: float, quant: str = "Q4") -> tuple[str, float, int]:
    family = _detect_family(model_ref)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_name, cost_hr, safe_ctx = _select_gpu_for_context(params_b, quant, desired_context, family)

    if family == "gpt_oss" and params_b >= 100:
        return gpu_name, cost_hr * 2, min(desired_context, limits["native_context"], safe_ctx)

    return gpu_name, cost_hr, min(desired_context, limits["native_context"], safe_ctx)


# Backward-compatible name used by existing scout callers
select_gpu = resolve_profile



def estimate_throughput(params_b: float) -> float:
    """Estimate tokens/sec for batched vLLM inference."""
    if params_b <= 7:
        return 200.0
    if params_b <= 14:
        return 120.0
    if params_b <= 30:
        return 100.0
    if params_b <= 40:
        return 80.0
    return 60.0



def estimate_cost_per_1m_tokens(model_ref: str | dict, params_b: float, quant: str = "Q4") -> tuple[float, float]:
    """Estimate cost per 1M tokens (input, output)."""
    _gpu_name, cost_hr, _ctx = select_gpu(model_ref, params_b, quant)
    throughput = estimate_throughput(params_b)
    cost_per_sec = cost_hr / 3600
    cost_per_1m = (cost_per_sec / throughput) * 1_000_000
    return round(cost_per_1m * 0.5, 4), round(cost_per_1m, 4)
