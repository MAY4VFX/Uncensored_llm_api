"""LLM-based analysis of model cards for quality assessment."""

import logging

import httpx

from scout.config import settings

logger = logging.getLogger(__name__)


async def analyze_model_card(model_id: str, model_card_text: str) -> dict | None:
    """
    Use Claude API to analyze a model card and extract structured info.
    Returns dict with: summary, quality_score (1-10), use_cases, concerns.
    """
    if not settings.anthropic_api_key:
        logger.warning("No Anthropic API key configured, skipping model card analysis")
        return None

    prompt = f"""Analyze this HuggingFace model card for the model "{model_id}".
Extract the following as JSON:
- "summary": Brief 1-2 sentence description of the model
- "quality_score": Score 1-10 based on documentation quality, training data clarity, and benchmark results
- "use_cases": List of 2-3 primary use cases
- "concerns": Any safety or quality concerns noted
- "base_model": The base model it was fine-tuned from, if mentioned

Model card text:
{model_card_text[:4000]}

Respond ONLY with valid JSON."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [{}])[0].get("text", "")

            import json
            return json.loads(content)
    except Exception as e:
        logger.error(f"Error analyzing model card for {model_id}: {e}")
        return None


async def fetch_model_card(model_id: str) -> str | None:
    """Fetch the README/model card from HuggingFace."""
    url = f"https://huggingface.co/{model_id}/raw/main/README.md"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        logger.error(f"Error fetching model card for {model_id}: {e}")
    return None
