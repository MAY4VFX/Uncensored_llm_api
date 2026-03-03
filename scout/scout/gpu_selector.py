"""GPU selection matrix based on model parameters and quantization."""

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}

GPU_OPTIONS = [
    ("RTX_4000_Ada_20GB", 8, 0.17),
    ("RTX_A4500_20GB", 16, 0.22),
    ("RTX_A5000_24GB", 24, 0.28),
    ("A100_40GB", 40, 1.19),
    ("A100_80GB", 80, 1.99),
]


def select_gpu(params_b: float, quant: str = "Q4") -> tuple[str, float]:
    """
    Select optimal GPU for a model.
    Returns (gpu_id, cost_per_hour).
    """
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    vram_needed = params_b * multiplier * 1.3  # 30% overhead

    for gpu_id, vram, cost_hr in GPU_OPTIONS:
        if vram_needed <= vram:
            return gpu_id, cost_hr

    # Fallback to largest
    return GPU_OPTIONS[-1][0], GPU_OPTIONS[-1][2]


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
    gpu_id, cost_hr = select_gpu(params_b, quant)
    throughput = estimate_throughput(params_b)
    cost_per_sec = cost_hr / 3600
    cost_per_1m = (cost_per_sec / throughput) * 1_000_000

    # Input is slightly cheaper (KV cache computation vs generation)
    return round(cost_per_1m * 0.5, 4), round(cost_per_1m, 4)
