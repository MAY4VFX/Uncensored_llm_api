from app.services.deploy_profile_service import resolve_deploy_profile


def test_qwen3_coder_prefers_agent_profile_defaults():
    metadata = {
        "id": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated",
        "tags": [
            "qwen3_moe",
            "abliterated",
            "uncensored",
            "base_model:Qwen/Qwen3-Coder-30B-A3B-Instruct",
        ],
        "cardData": {
            "base_model": ["Qwen/Qwen3-Coder-30B-A3B-Instruct"],
        },
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=30.5, quantization="FP16")

    assert profile["family"] == "qwen3_coder"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["target_context"] >= 131072
    assert profile["tool_parser"] != "hermes"
    assert profile["default_temperature"] <= 0.2


def test_gpt_oss_prefers_h200_openai_and_128k_context():
    metadata = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "tags": [
            "gpt_oss",
            "uncensored",
            "reasoning",
            "base_model:openai/gpt-oss-120b",
        ],
        "cardData": {
            "base_model": ["openai/gpt-oss-120b"],
        },
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=117.0, quantization="FP16")

    assert profile["family"] == "gpt_oss"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["target_context"] >= 128000
    assert profile["tool_parser"] == "openai"
    assert profile["docker_image"] == "vllm/vllm-openai:gptoss"
    assert profile["default_temperature"] <= 0.2



def test_unknown_model_uses_conservative_fallback_profile():
    metadata = {
        "id": "someone/unknown-model",
        "tags": ["text-generation"],
        "cardData": {},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=7, quantization="FP16")

    assert profile["family"] == "fallback"
    assert profile["gpu_type"]
    assert profile["target_context"] >= 4096
    assert profile["tool_parser"] == "hermes"



def test_gpt_oss_detects_base_model_without_repo_name_hint():
    metadata = {
        "id": "ArliAI/Derestricted-Reasoner",
        "tags": ["reasoning", "base_model:openai/gpt-oss-20b"],
        "cardData": {"base_model": ["openai/gpt-oss-20b"]},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=21.0, quantization="FP16")

    assert profile["family"] == "gpt_oss"
    assert profile["tool_parser"] == "openai"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["target_context"] >= 128000



def test_gpt_oss_prefers_h200_even_if_smaller_gpu_could_fit_weights():
    metadata = {
        "id": "openai/gpt-oss-20b",
        "tags": ["gpt_oss"],
        "cardData": {"base_model": ["openai/gpt-oss-20b"]},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=20.0, quantization="Q8")

    assert profile["family"] == "gpt_oss"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["target_context"] >= 128000
    assert profile["tool_parser"] == "openai"
