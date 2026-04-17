"""HuggingFace Hub API client for discovering uncensored models."""

import logging
import re

import httpx

from scout.config import settings

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"

SEARCH_TERMS = [
    "uncensored",
    "abliterated",
    "heretic",
    "unfiltered",
    "unrestricted",
    "decensored",
    "no-refusal",
    "unaligned",
    "fallen",
    "distilled",
    "reasoning",
]
VALID_FORMATS = {"safetensors", "gguf"}
MIN_PARAMS_B = 2.0
MAX_PARAMS_B = 130.0


def _headers() -> dict:
    headers = {}
    if settings.hf_token:
        headers["Authorization"] = f"Bearer {settings.hf_token}"
    return headers


async def search_models(limit: int = 50) -> list[dict]:
    """Search HuggingFace Hub for uncensored/abliterated text-generation models."""
    all_models = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=30) as client:
        for term in SEARCH_TERMS:
            try:
                resp = await client.get(
                    f"{HF_API_BASE}/models",
                    params={
                        "search": term,
                        "sort": "lastModified",
                        "direction": "-1",
                        "limit": limit,
                        "pipeline_tag": "text-generation",
                    },
                    headers=_headers(),
                )
                resp.raise_for_status()
                models = resp.json()

                for m in models:
                    model_id = m.get("id", "")
                    if model_id not in seen_ids:
                        seen_ids.add(model_id)
                        all_models.append(m)
            except Exception as e:
                logger.error(f"Error searching HF Hub for '{term}': {e}")

    return all_models


def filter_models(
    models: list[dict],
    min_downloads: int = 100,
    min_likes: int = 5,
) -> list[dict]:
    """Filter models by quality criteria."""
    filtered = []

    for m in models:
        downloads = m.get("downloads", 0)
        likes = m.get("likes", 0)
        tags = [t.lower() for t in m.get("tags", [])]

        # Check downloads and likes
        if downloads < min_downloads or likes < min_likes:
            continue

        # Check for valid format
        has_valid_format = any(fmt in tags for fmt in VALID_FORMATS)
        if not has_valid_format:
            # Also accept safetensors if it's in siblings
            siblings = m.get("siblings", [])
            for s in siblings:
                fname = s.get("rfilename", "")
                if fname.endswith(".safetensors") or fname.endswith(".gguf"):
                    has_valid_format = True
                    break

        if not has_valid_format:
            continue

        filtered.append(m)

    return filtered


def extract_params_b(model_data: dict) -> float | None:
    """Try to extract model size in billions from tags or model name."""
    model_id = model_data.get("id", "")
    tags = model_data.get("tags", [])

    # Check safetensors metadata
    safetensors = model_data.get("safetensors", {})
    if safetensors:
        total_params = safetensors.get("total", 0)
        if total_params > 0:
            return round(total_params / 1e9, 1)

    # Try to extract from model name (e.g., "7B", "70b", "13b")
    pattern = r"(\d+(?:\.\d+)?)\s*[bB]"
    match = re.search(pattern, model_id)
    if match:
        return float(match.group(1))

    # Check tags for size hints
    for tag in tags:
        match = re.search(pattern, tag)
        if match:
            return float(match.group(1))

    return None


def determine_quantization(model_data: dict) -> str:
    """Determine quantization from tags or file names."""
    tags = [t.lower() for t in model_data.get("tags", [])]

    if "gguf" in tags:
        return "Q4"  # Default GGUF assumption

    siblings = model_data.get("siblings", [])
    for s in siblings:
        fname = s.get("rfilename", "").lower()
        if "q4" in fname:
            return "Q4"
        elif "q8" in fname:
            return "Q8"
        elif "fp16" in fname or "f16" in fname:
            return "FP16"

    return "FP16"  # Default for safetensors
