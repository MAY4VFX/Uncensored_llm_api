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
