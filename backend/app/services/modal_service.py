from __future__ import annotations

from typing import Any

from app.models.llm_model import LlmModel


class ModalProviderError(RuntimeError):
    pass


async def deploy_model(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, Any]:
    image = (
        (model.provider_config or {}).get("image")
        or default_image
        or profile.get("modal_image")
        or "modal-vllm-runtime:latest"
    )
    deployment_ref = f"modal:{model.slug}"
    return {
        "deployment_ref": deployment_ref,
        "provider_status": "provisioning",
        "image": image,
        "profile": {
            "family": profile.get("family"),
            "gpu_type": profile.get("gpu_type"),
            "gpu_count": profile.get("gpu_count"),
            "target_context": profile.get("target_context"),
        },
    }


async def redeploy_model(model: LlmModel, profile: dict[str, Any], default_image: str | None = None) -> dict[str, Any]:
    return await deploy_model(model, profile, default_image=default_image)


async def disable_model(model: LlmModel) -> dict[str, Any]:
    return {
        "deployment_ref": model.deployment_ref,
        "provider_status": "inactive",
    }


def supports_runtime(profile: dict[str, Any]) -> bool:
    return profile.get("family") != "gguf"
