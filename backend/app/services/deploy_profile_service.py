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
    "gpt_oss": {
        "native_context": 128000,
        "practical_cap": 128000,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "openai",
        "docker_image": "vllm/vllm-openai:v0.11.2",
        "default_temperature": 0.2,
        "runtime_args": {
            "max_num_batched_tokens": 1024,
        },
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


def _extract_base_text(metadata: dict, tags: list[str]) -> str:
    card = metadata.get("cardData") or {}
    base_model = card.get("base_model") or []
    if isinstance(base_model, str):
        base_model = [base_model]

    tag_base_models = [
        tag.split(":", 1)[1]
        for tag in tags
        if tag.startswith("base_model:") and ":" in tag
    ]
    return " ".join(str(x).lower() for x in [*base_model, *tag_base_models])



def _detect_family(metadata: dict) -> str:
    repo = (metadata.get("id") or "").lower()
    tags = [str(t).lower() for t in metadata.get("tags", [])]
    base_text = _extract_base_text(metadata, tags)

    if "gguf" in tags:
        return "gguf"
    if (
        "gpt-oss" in repo
        or "gpt-oss" in base_text
        or "gpt_oss" in tags
        or "gpt-oss" in tags
    ):
        return "gpt_oss"
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



def _detect_gpt_oss_size_class(metadata: dict, params_b: float) -> str:
    repo = (metadata.get("id") or "").lower()
    tags = [str(t).lower() for t in metadata.get("tags", [])]
    base_text = _extract_base_text(metadata, tags)

    if "gpt-oss-120b" in repo or "gpt-oss-120b" in base_text or params_b >= 100:
        return "120b"
    return "20b"


def _estimate_safe_context(params_b: float, quantization: str, vram_gb: int, family: str) -> int:
    multiplier = QUANT_MULTIPLIERS.get(quantization, 1.0)

    if family == "gpt_oss":
        effective_params_b = min(params_b, 22.0)
        weight_budget = effective_params_b * multiplier * 1.15
    else:
        weight_budget = params_b * multiplier * 1.15

    free_vram = vram_gb - weight_budget
    if free_vram <= 0:
        return 4096

    if family.startswith("qwen3"):
        kv_per_4k = max(params_b * 0.045, 1.0)
    elif family == "gpt_oss":
        kv_per_4k = max(params_b * 0.02, 1.0)
    else:
        kv_per_4k = max(params_b * 0.5, 1.0)

    ctx = int((free_vram / kv_per_4k) * 4096)
    ctx = (ctx // 1024) * 1024
    return max(ctx, 4096)



def _safe_context_on_gpu(params_b: float, quantization: str, gpu_type: str, family: str) -> int:
    vram_gb = next(vram for name, vram in GPU_OPTIONS if name == gpu_type)
    return _estimate_safe_context(params_b, quantization, vram_gb, family)



def _coerce_minimum_context(family: str, gpu_type: str, computed_context: int) -> int:
    minimums = {
        ("qwen3_coder", "H200_141GB"): 204800,
        ("qwen3_general", "H200_141GB"): 131072,
        ("gpt_oss", "H200_141GB"): 128000,
    }
    return max(computed_context, minimums.get((family, gpu_type), 4096))



def _select_gpu_for_context(params_b: float, quantization: str, desired_context: int, family: str) -> tuple[str, int]:
    preferred_gpu = FAMILY_LIMITS[family].get("preferred_gpu")
    if preferred_gpu:
        preferred_context = _coerce_minimum_context(
            family,
            preferred_gpu,
            _safe_context_on_gpu(params_b, quantization, preferred_gpu, family),
        )
        if preferred_context >= desired_context:
            return preferred_gpu, 1

    for gpu_type, _vram_gb in GPU_OPTIONS:
        safe_context = _coerce_minimum_context(
            family,
            gpu_type,
            _safe_context_on_gpu(params_b, quantization, gpu_type, family),
        )
        if safe_context >= desired_context:
            return gpu_type, 1

    return "H200_141GB", 1



def resolve_deploy_profile(metadata: dict, params_b: float, quantization: str) -> dict:
    family = _detect_family(metadata)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_type, gpu_count = _select_gpu_for_context(params_b, quantization, desired_context, family)
    safe_context = _safe_context_on_gpu(params_b, quantization, gpu_type, family)
    safe_context = _coerce_minimum_context(family, gpu_type, safe_context)
    target_context = min(desired_context, limits["native_context"], safe_context)

    docker_image = limits.get("docker_image", "")
    if not docker_image and family == "gguf":
        docker_image = "may4vfx/worker-llamacpp:latest"

    runtime_args = dict(limits.get("runtime_args", {}))

    if family == "gpt_oss":
        size_class = _detect_gpt_oss_size_class(metadata, params_b)
        if size_class == "120b":
            gpu_count = 2
            runtime_args["tensor_parallel_size"] = 2
        else:
            gpu_count = 1
            runtime_args["tensor_parallel_size"] = 1

    # For large models, the first cold start can take 8+ minutes because the
    # worker downloads weights from HuggingFace. RunPod's default execution
    # timeout (~10 min) then kills the worker mid-load, and it tries again,
    # burning money in a loop. Give big models a 30-minute ceiling and flag
    # them as needing a network volume so weights persist across cold starts.
    approx_weight_gb = params_b * QUANT_MULTIPLIERS.get(quantization, 1.0) * 2  # bytes/param → GB is ~1:1 scale
    if params_b >= 60 or approx_weight_gb >= 80:
        execution_timeout_ms = 1_800_000  # 30 min
        recommended_volume_gb = max(200, int(approx_weight_gb * 1.5) + 50)
    else:
        execution_timeout_ms = 600_000  # 10 min (RunPod default)
        recommended_volume_gb = 0  # small enough to re-download on each cold start

    return {
        "family": family,
        "gpu_type": gpu_type,
        "gpu_count": gpu_count,
        "target_context": target_context,
        "tool_parser": limits["tool_parser"],
        "docker_image": docker_image,
        "default_temperature": limits["default_temperature"],
        "generation_config_mode": "vllm",
        "enable_prefix_caching": True,
        "enable_chunked_prefill": True,
        "runtime_args": runtime_args,
        "execution_timeout_ms": execution_timeout_ms,
        "recommended_volume_gb": recommended_volume_gb,
    }
