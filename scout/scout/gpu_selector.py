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
    "qwen3_coder": {"native_context": 262144, "practical_cap": 262144},
    "qwen3_general": {"native_context": 131072, "practical_cap": 204800},
    "fallback": {"native_context": 32768, "practical_cap": 65536},
}


def _detect_family(hf_repo: str) -> str:
    repo = (hf_repo or "").lower()
    if "qwen3" in repo and "coder" in repo:
        return "qwen3_coder"
    if "qwen3" in repo:
        return "qwen3_general"
    return "fallback"


def _estimate_safe_context(params_b: float, quant: str, vram_gb: float, family: str) -> int:
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    model_vram = params_b * multiplier * 1.15
    free_vram = vram_gb - model_vram
    if free_vram <= 0:
        return 4096

    # Qwen3 MoE models have a much smaller active KV footprint than a naive
    # dense-parameter approximation suggests. This heuristic matches observed
    # behavior on our current H200 deployments much better than the old formula.
    kv_per_4k = params_b * (0.045 if family.startswith("qwen3") else 0.5)
    max_ctx = int((free_vram / max(kv_per_4k, 1.0)) * 4096)
    max_ctx = (max_ctx // 1024) * 1024
    return min(max(max_ctx, 2048), 262144)


def _safe_context_on_gpu(params_b: float, quant: str, gpu_name: str, family: str) -> int:
    for name, vram, _cost_hr, _pool in GPU_OPTIONS:
        if name == gpu_name:
            ctx = _estimate_safe_context(params_b, quant, vram, family)
            if family == "qwen3_coder" and gpu_name == "H200_141GB":
                return max(ctx, 204800)
            return ctx
    return 4096


def _select_gpu_for_context(params_b: float, quant: str, desired_context: int, family: str) -> tuple[str, float, int]:
    for gpu_name, _vram, cost_hr, _pool in GPU_OPTIONS:
        safe_ctx = _safe_context_on_gpu(params_b, quant, gpu_name, family)
        if safe_ctx >= desired_context:
            return gpu_name, cost_hr, safe_ctx

    gpu_name, _vram, cost_hr, _pool = GPU_OPTIONS[-1]
    return gpu_name, cost_hr, _safe_context_on_gpu(params_b, quant, gpu_name, family)


def resolve_profile(hf_repo: str, params_b: float, quant: str = "Q4") -> tuple[str, float, int]:
    family = _detect_family(hf_repo)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_name, cost_hr, safe_ctx = _select_gpu_for_context(params_b, quant, desired_context, family)
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


def estimate_cost_per_1m_tokens(params_b: float, quant: str = "Q4") -> tuple[float, float]:
    """Estimate cost per 1M tokens (input, output)."""
    _gpu_name, cost_hr, _ctx = select_gpu("unknown", params_b, quant)
    throughput = estimate_throughput(params_b)
    cost_per_sec = cost_hr / 3600
    cost_per_1m = (cost_per_sec / throughput) * 1_000_000
    return round(cost_per_1m * 0.5, 4), round(cost_per_1m, 4)
