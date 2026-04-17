from scout.gpu_selector import resolve_profile, resolve_tool_parser
from scout.hf_client import MAX_PARAMS_B, extract_params_b


def test_hf_client_allows_117b_gpt_oss_models():
    metadata = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "safetensors": {"total": 117_000_000_000},
    }

    assert MAX_PARAMS_B >= 117.0
    assert extract_params_b(metadata) == 117.0



def test_gpt_oss_profile_prefers_h200_and_128k_context():
    gpu_type, _cost_hr, max_context = resolve_profile(
        "ArliAI/gpt-oss-120b-Derestricted",
        117.0,
        "FP16",
    )

    assert gpu_type == "H200_141GB"
    assert max_context >= 128000



def test_gpt_oss_profile_detects_openai_base_family():
    gpu_type, _cost_hr, max_context = resolve_profile(
        "openai/gpt-oss-20b",
        20.0,
        "Q8",
    )

    assert gpu_type == "H200_141GB"
    assert max_context >= 128000
    assert resolve_tool_parser("openai/gpt-oss-20b") == "openai"



def test_qwen3_coder_parser_mapping_unchanged():
    assert resolve_tool_parser("huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated") == "qwen3_coder"



def test_fallback_parser_mapping_unchanged():
    assert resolve_tool_parser("some-org/unknown-model") == "hermes"
