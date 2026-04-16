from __future__ import annotations

GPU_OPTIONS = [
    ("A100_80GB", 80),
    ("H100_80GB", 80),
    ("H200_141GB", 141),
]

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}

FAMILY_LIMITS = {
    "qwen3_coder": {
        "native_context": 262144,
        "practical_cap": 262144,
        "preferred_gpu": "H200_141GB",
        # Qwen3-Coder is trained on the <function=name><parameter=...>...</parameter></function>
        # XML tool format. vLLM's `qwen3_coder` parser handles that exact dialect.
        # `qwen3_xml` parses the generic <tool_call>{...}</tool_call> wrapper and
        # silently misses tool calls under long agent prompts (opencode bug #1809,
        # vLLM/opencode #16488).
        "tool_parser": "qwen3_coder",
        "default_temperature": 0.2,
    },
    "qwen3_general": {
        "native_context": 131072,
        "practical_cap": 204800,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "hermes",
        "default_temperature": 0.2,
    },
    "glm": {
        "native_context": 131072,
        "practical_cap": 131072,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "glm45",
        "default_temperature": 0.2,
    },
    "deepseek": {
        "native_context": 131072,
        "practical_cap": 131072,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "hermes",
        "default_temperature": 0.2,
    },
    "gguf": {
        "native_context": 131072,
        "practical_cap": 131072,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "none",
        "default_temperature": 0.2,
    },
    "fallback": {
        "native_context": 32768,
        "practical_cap": 65536,
        "preferred_gpu": "A100_80GB",
        "tool_parser": "hermes",
        "default_temperature": 0.2,
    },
}


def _detect_family(metadata: dict) -> str:
    repo = (metadata.get("id") or "").lower()
    tags = [t.lower() for t in metadata.get("tags", [])]
    card = metadata.get("cardData") or {}
    base_model = card.get("base_model") or []
    if isinstance(base_model, str):
        base_model = [base_model]
    base_text = " ".join(str(x).lower() for x in base_model)

    if "gguf" in tags:
        return "gguf"
    if "coder" in repo or "coder" in base_text:
        if "qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags:
            return "qwen3_coder"
    if "qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags:
        return "qwen3_general"
    if "glm" in repo or "glm" in base_text:
        return "glm"
    if "deepseek" in repo or "deepseek" in base_text:
        return "deepseek"
    return "fallback"


def _estimate_safe_context(params_b: float, quantization: str, vram_gb: int, family: str) -> int:
    multiplier = QUANT_MULTIPLIERS.get(quantization, 1.0)
    weight_budget = params_b * multiplier * 1.15
    free_vram = vram_gb - weight_budget
    if free_vram <= 0:
        return 4096

    # Qwen3 MoE models have much smaller active KV footprint than a naive
    # dense-params formula suggests. Use a family-aware heuristic that matches
    # observed behavior on current H200 deployments.
    if family.startswith("qwen3"):
        kv_per_4k = max(params_b * 0.045, 1.0)
    else:
        kv_per_4k = max(params_b * 0.5, 1.0)

    ctx = int((free_vram / kv_per_4k) * 4096)
    ctx = (ctx // 1024) * 1024
    return max(ctx, 4096)


def _safe_context_on_gpu(params_b: float, quantization: str, gpu_type: str, family: str) -> int:
    vram_gb = next(vram for name, vram in GPU_OPTIONS if name == gpu_type)
    return _estimate_safe_context(params_b, quantization, vram_gb, family)


def _select_gpu_for_context(params_b: float, quantization: str, desired_context: int, family: str) -> tuple[str, int]:
    for gpu_type, _vram_gb in GPU_OPTIONS:
        if _safe_context_on_gpu(params_b, quantization, gpu_type, family) >= desired_context:
            return gpu_type, 1
    return "H200_141GB", 1


def _coerce_minimum_context(family: str, gpu_type: str, computed_context: int) -> int:
    minimums = {
        ("qwen3_coder", "H200_141GB"): 204800,
        ("qwen3_general", "H200_141GB"): 131072,
    }
    return max(computed_context, minimums.get((family, gpu_type), 4096))


def resolve_deploy_profile(metadata: dict, params_b: float, quantization: str) -> dict:
    family = _detect_family(metadata)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_type, gpu_count = _select_gpu_for_context(params_b, quantization, desired_context, family)
    safe_context = _safe_context_on_gpu(params_b, quantization, gpu_type, family)
    safe_context = _coerce_minimum_context(family, gpu_type, safe_context)
    target_context = min(desired_context, limits["native_context"], safe_context)

    return {
        "family": family,
        "gpu_type": gpu_type,
        "gpu_count": gpu_count,
        "target_context": target_context,
        "tool_parser": limits["tool_parser"],
        "default_temperature": limits["default_temperature"],
        "generation_config_mode": "vllm",
        "enable_prefix_caching": True,
        "enable_chunked_prefill": True,
    }


