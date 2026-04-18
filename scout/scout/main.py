"""Model Scout Agent — discovers and auto-deploys uncensored LLM models from HuggingFace."""

import asyncio
import logging
import re

from apscheduler.schedulers.blocking import BlockingScheduler

from scout.analyzer import analyze_model_card, fetch_model_card
from scout.config import settings
from scout.db import (
    get_session,
    insert_model,
    model_exists,
    should_auto_deploy_runpod,
    update_hf_stats,
    update_model_status,
)
from scout.deployer import deploy_endpoint
from scout.gpu_selector import estimate_cost_per_1m_tokens, select_gpu
from scout.hf_client import (
    MAX_PARAMS_B,
    MIN_PARAMS_B,
    determine_quantization,
    extract_params_b,
    filter_models,
    search_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _slugify(model_id: str) -> str:
    """Convert HF model ID to a URL-safe slug."""
    slug = model_id.lower().replace("/", "--")
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


async def scout_run():
    """Main scout run: search, filter, analyze, deploy."""
    logger.info("Starting scout run...")

    # 1. Search HuggingFace
    raw_models = await search_models(limit=50)
    logger.info(f"Found {len(raw_models)} raw models from HF Hub")

    # 2. Filter by quality
    filtered = filter_models(
        raw_models,
        min_downloads=settings.scout_min_downloads,
        min_likes=settings.scout_min_likes,
    )
    logger.info(f"After filtering: {len(filtered)} models")

    session = get_session()
    new_count = 0

    try:
        for m in filtered:
            hf_repo = m.get("id", "")

            # Update HF stats for existing models
            if model_exists(session, hf_repo):
                downloads = m.get("downloads", 0)
                likes = m.get("likes", 0)
                update_hf_stats(session, hf_repo, downloads, likes)
                continue

            # Extract metadata
            params_b = extract_params_b(m)
            if params_b is None or params_b < MIN_PARAMS_B or params_b > MAX_PARAMS_B:
                continue

            quant = determine_quantization(m)
            gpu_type, _, max_context = select_gpu(m, params_b, quant)
            gpu_count = 2 if ("gpt-oss-120b" in hf_repo.lower() or params_b >= 100) else 1
            cost_input, cost_output = estimate_cost_per_1m_tokens(m, params_b, quant)
            slug = _slugify(hf_repo)

            downloads = m.get("downloads", 0)
            likes = m.get("likes", 0)

            # Analyze model card (optional)
            description = None
            model_card = await fetch_model_card(hf_repo)
            if model_card:
                analysis = await analyze_model_card(hf_repo, model_card)
                if analysis:
                    description = analysis.get("summary", "")

            # Determine auto-deploy eligibility
            auto_deploy = (
                downloads >= settings.scout_auto_deploy_min_downloads
                and likes >= settings.scout_auto_deploy_min_likes
            )

            model_data = {
                "slug": slug,
                "display_name": hf_repo.split("/")[-1],
                "hf_repo": hf_repo,
                "params_b": params_b,
                "quantization": quant,
                "gpu_type": gpu_type,
                "gpu_count": gpu_count,
                "max_context_length": max_context,
                "cost_per_1m_input": cost_input,
                "cost_per_1m_output": cost_output,
                "description": description,
                "hf_downloads": downloads,
                "hf_likes": likes,
                "status": "pending",
            }

            db_model = insert_model(session, model_data)
            new_count += 1
            logger.info(f"Added model: {hf_repo} (params={params_b}B, gpu={gpu_type})")

            # Auto-deploy only on the real RunPod path. Modal remains backend-managed.
            if auto_deploy and should_auto_deploy_runpod(session, db_model.provider_override):
                logger.info(f"Auto-deploying {hf_repo} to RunPod...")
                update_model_status(session, db_model.id, "deploying")
                endpoint_id = await deploy_endpoint(
                    name=f"unch-{slug[:40]}",
                    gpu_type=gpu_type,
                    hf_repo=hf_repo,
                    max_model_len=max_context,
                    gpu_count=gpu_count,
                )
                if endpoint_id:
                    update_model_status(session, db_model.id, "active", endpoint_id)
                    logger.info(f"Deployed {hf_repo} → endpoint {endpoint_id}")
                else:
                    update_model_status(session, db_model.id, "pending")
                    logger.error(f"Failed to deploy {hf_repo}")
            elif auto_deploy:
                logger.info(f"Skipping direct scout auto-deploy for {hf_repo}: provider is modal/backend-managed")

    finally:
        session.close()

    logger.info(f"Scout run complete. {new_count} new models added.")


def run_scout_sync():
    """Synchronous wrapper for the scout run."""
    asyncio.run(scout_run())


def main():
    logger.info(f"Starting Model Scout Agent (interval: {settings.scout_interval_hours}h)")

    # Run once immediately
    run_scout_sync()

    # Schedule recurring runs
    scheduler = BlockingScheduler()
    scheduler.add_job(run_scout_sync, "interval", hours=settings.scout_interval_hours)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scout agent stopped.")


if __name__ == "__main__":
    main()
