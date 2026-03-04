"""GPU selection matrix based on model parameters, quantization, and context length."""

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}

# (primary_gpu_id, vram_gb, cost_per_hour, runpod_pool_ids)
# pool_ids: comma-separated RunPod pool IDs for fallback availability
GPU_OPTIONS = [
    ("RTX_4000_Ada_20GB", 8, 0.17, "AMPERE_16"),
    ("RTX_A4500_20GB", 16, 0.22, "AMPERE_16"),
    ("RTX_A5000_24GB", 24, 0.28, "ADA_24,AMPERE_24"),
    ("A100_40GB", 48, 1.19, "AMPERE_48,ADA_48_PRO"),
    ("A100_80GB", 80, 1.99, "AMPERE_80,ADA_80_PRO,HOPPER_141"),
]


def _estimate_kv_cache_gb(params_b: float, context_length: int) -> float:
    """Estimate KV cache VRAM in GB.

    KV cache per layer ≈ 2 * num_heads * head_dim * context_length * 2 bytes (fp16)
    Rough formula: ~0.5 GB per 1B params per 4096 context tokens.
    """
    return params_b * (context_length / 4096) * 0.5


def _max_context_for_gpu(params_b: float, quant: str, vram_gb: float) -> int:
    """Calculate max context length that fits in given VRAM."""
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    model_vram = params_b * multiplier * 1.15  # 15% overhead for model weights
    free_vram = vram_gb - model_vram

    if free_vram <= 0:
        return 0

    # KV cache: ~0.5 GB per 1B params per 4096 tokens
    kv_per_4k = params_b * 0.5
    if kv_per_4k <= 0:
        return 4096

    max_ctx = int((free_vram / kv_per_4k) * 4096)
    # Round down to nearest 1024, cap at reasonable limits
    max_ctx = (max_ctx // 1024) * 1024
    return min(max(max_ctx, 2048), 131072)


def select_gpu(params_b: float, quant: str = "Q4") -> tuple[str, float, int]:
    """
    Select optimal GPU for a model with maximum context.
    Returns (runpod_pool_ids, cost_per_hour, max_context_length).
    Picks the smallest GPU that fits model weights + at least 8192 context.
    """
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    model_vram = params_b * multiplier * 1.15

    fallback = None
    for _, vram, cost_hr, pool_ids in GPU_OPTIONS:
        max_ctx = _max_context_for_gpu(params_b, quant, vram)
        if model_vram < vram and max_ctx >= 4096:
            # Prefer GPU that can do at least 8192 context
            if max_ctx >= 8192:
                return pool_ids, cost_hr, max_ctx
            # Accept 4096 if no better option
            if fallback is None:
                fallback = (pool_ids, cost_hr, max_ctx)

    # If we found a 4096-capable GPU but nothing bigger
    if fallback is not None:
        return fallback

    # Fallback to largest GPU
    _, vram, cost_hr, pool_ids = GPU_OPTIONS[-1]
    max_ctx = _max_context_for_gpu(params_b, quant, vram)
    return pool_ids, cost_hr, max(max_ctx, 4096)


def estimate_throughput(params_b: float) -> float:
    """Estimate tokens/sec for batched vLLM inference."""
    if params_b <= 7:
        return 200.0
    elif params_b <= 14:
        return 120.0
    elif params_b <= 30:
        return 100.0
    elif params_b <= 40:
        return 80.0
    else:
        return 60.0


def estimate_cost_per_1m_tokens(params_b: float, quant: str = "Q4") -> tuple[float, float]:
    """
    Estimate cost per 1M tokens (input, output).
    Returns (cost_1m_input, cost_1m_output).
    """
    _pool_ids, cost_hr, _ctx = select_gpu(params_b, quant)
    throughput = estimate_throughput(params_b)
    cost_per_sec = cost_hr / 3600
    cost_per_1m = (cost_per_sec / throughput) * 1_000_000

    # Input is slightly cheaper (KV cache computation vs generation)
    return round(cost_per_1m * 0.5, 4), round(cost_per_1m, 4)
