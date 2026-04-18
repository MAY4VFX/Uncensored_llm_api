import re
import uuid

import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_admin_user
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.model import (
    AddFromHfRequest,
    AppSettingsResponse,
    AvailableProviderResponse,
    AvailableProvidersResponse,
    CanaryInventoryResponse,
    CreateModelRequest,
    DeployModelResponse,
    DiscoverySummaryResponse,
    ImageInventoryItem,
    ImageInventoryResponse,
    ModelOptionResponse,
    ModelResponse,
    ProviderCapabilitiesResponse,
    RedeployModelResponse,
    ResolveProviderRequest,
    ResolveProviderResponse,
    UpdateAppSettingsRequest,
    UpdateModelRequest,
    UpdateModelStatusRequest,
    UpdateModelStatusResponse,
)
from app.services.deploy_profile_service import resolve_deploy_profile
from app.services.modal_service import disable_model as disable_modal_model
from app.services.modal_service import deploy_model as deploy_modal_model
from app.services.modal_service import get_status as get_modal_status
from app.services.modal_service import redeploy_model as redeploy_modal_model
from app.services.modal_service import supports_runtime as modal_supports_runtime
from app.services.provider_service import (
    MODAL,
    RUNPOD,
    SUPPORTED_PROVIDERS,
    get_or_create_app_settings,
    get_provider_capabilities,
    normalize_provider_override,
    resolve_model_provider,
)
from app.services.runpod_service import create_endpoint, delete_endpoint

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

GPU_MATRIX = {
    "RTX_4000_Ada_20GB": 8,
    "RTX_A5000_24GB": 24,
    "A100_80GB": 80,
    "H100_80GB": 80,
    "H200_141GB": 141,
}

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}


PROVIDER_LABELS = {
    RUNPOD: "RunPod",
    MODAL: "Modal",
}


def _capabilities_response(provider: str) -> ProviderCapabilitiesResponse:
    return ProviderCapabilitiesResponse(**get_provider_capabilities(provider))


async def _to_model_response(model: LlmModel, db: AsyncSession) -> ModelResponse:
    effective_provider = await resolve_model_provider(model, db)
    return ModelResponse(
        id=model.id,
        slug=model.slug,
        display_name=model.display_name,
        hf_repo=model.hf_repo,
        params_b=float(model.params_b),
        quantization=model.quantization,
        gpu_type=model.gpu_type,
        gpu_count=model.gpu_count,
        max_context_length=model.max_context_length,
        status=model.status,
        provider_status=model.provider_status,
        provider_override=model.provider_override,
        effective_provider=effective_provider,
        provider_config=model.provider_config,
        deployment_ref=model.deployment_ref,
        runpod_endpoint_id=model.runpod_endpoint_id,
        cost_per_1m_input=float(model.cost_per_1m_input),
        cost_per_1m_output=float(model.cost_per_1m_output),
        description=model.description,
        system_prompt=model.system_prompt,
        hf_downloads=model.hf_downloads,
        hf_likes=model.hf_likes,
        capabilities=_capabilities_response(effective_provider),
        created_at=model.created_at,
    )


async def _app_settings_response(db: AsyncSession) -> AppSettingsResponse:
    settings = await get_or_create_app_settings(db)
    return AppSettingsResponse(
        default_provider=settings.default_provider,
        modal_default_image=settings.modal_default_image,
        runpod_default_image=settings.runpod_default_image,
        provider_flags=settings.provider_flags,
        supported_providers=sorted(SUPPORTED_PROVIDERS),
    )


def select_gpu(params_b: float, quant: str) -> tuple[str, int]:
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    vram_needed = params_b * multiplier * 1.3
    for gpu_name, vram in GPU_MATRIX.items():
        if vram_needed <= vram:
            return gpu_name, 1
    best_gpu = "H200_141GB"
    best_vram = GPU_MATRIX[best_gpu]
    gpu_count = max(1, -(-int(vram_needed) // best_vram))
    gpu_count = min(gpu_count, 8)
    return best_gpu, gpu_count


@router.get("/settings/providers", response_model=AppSettingsResponse)
async def get_provider_settings(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await _app_settings_response(db)


@router.patch("/settings/providers", response_model=AppSettingsResponse)
async def update_provider_settings(
    request: UpdateAppSettingsRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_app_settings(db)
    updates = request.model_dump(exclude_unset=True)

    if "default_provider" in updates and updates["default_provider"] is not None:
        provider = updates["default_provider"]
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider '{provider}'")
        settings.default_provider = provider

    if "modal_default_image" in updates:
        settings.modal_default_image = updates["modal_default_image"]
    if "runpod_default_image" in updates:
        settings.runpod_default_image = updates["runpod_default_image"]
    if "provider_flags" in updates:
        settings.provider_flags = updates["provider_flags"]

    await db.commit()
    await db.refresh(settings)
    return await _app_settings_response(db)


@router.get("/providers", response_model=AvailableProvidersResponse)
async def list_providers(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_app_settings(db)
    return AvailableProvidersResponse(
        default_provider=settings.default_provider,
        providers=[
            AvailableProviderResponse(
                id=provider,
                label=PROVIDER_LABELS[provider],
                capabilities=_capabilities_response(provider),
            )
            for provider in sorted(SUPPORTED_PROVIDERS)
        ],
    )


@router.post("/providers/resolve", response_model=ResolveProviderResponse)
async def resolve_provider_preview(
    request: ResolveProviderRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"https://huggingface.co/api/models/{request.hf_repo.strip()}")
        resp.raise_for_status()
        metadata = resp.json()

    profile = resolve_deploy_profile(metadata, params_b=request.params_b, quantization=request.quantization)
    settings = await get_or_create_app_settings(db)
    effective_provider = normalize_provider_override(request.provider_override) or settings.default_provider
    warnings: list[str] = []
    can_deploy = True

    if effective_provider == MODAL and not modal_supports_runtime(profile):
        can_deploy = False
        warnings.append("Modal v1 currently supports only vLLM families; GGUF remains RunPod-only.")

    return ResolveProviderResponse(
        effective_provider=effective_provider,
        capabilities=_capabilities_response(effective_provider),
        family=profile["family"],
        warnings=warnings,
        can_deploy=can_deploy,
        profile=profile,
    )


@router.get("/models", response_model=list[ModelResponse])
async def list_all_models(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).order_by(LlmModel.created_at.desc()))
    models = result.scalars().all()
    return [await _to_model_response(model, db) for model in models]


@router.get("/models/pending", response_model=list[ModelResponse])
async def list_pending_models(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LlmModel).where(LlmModel.status == "pending").order_by(LlmModel.created_at.desc())
    )
    models = result.scalars().all()
    return [await _to_model_response(model, db) for model in models]


@router.post("/models/backfill-runpod-overrides")
async def backfill_runpod_overrides(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).where(LlmModel.provider_override.is_(None)))
    models = result.scalars().all()
    updated = 0
    for model in models:
        model.provider_override = RUNPOD
        updated += 1
    await db.commit()
    return {"updated": updated, "detail": "Pinned existing models to runpod override"}


@router.post("/models", response_model=ModelResponse)
async def create_model(
    request: CreateModelRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(LlmModel).where(LlmModel.slug == request.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Model slug already exists")

    gpu_type, gpu_count = select_gpu(request.params_b, request.quantization)
    model = LlmModel(
        slug=request.slug,
        display_name=request.display_name,
        hf_repo=request.hf_repo,
        params_b=request.params_b,
        quantization=request.quantization,
        gpu_type=gpu_type,
        gpu_count=gpu_count,
        cost_per_1m_input=request.cost_per_1m_input,
        cost_per_1m_output=request.cost_per_1m_output,
        description=request.description,
        provider_override=normalize_provider_override(request.provider_override),
        provider_config=request.provider_config,
        status="pending",
        provider_status="pending",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return await _to_model_response(model, db)


def _slugify(model_id: str) -> str:
    slug = model_id.lower().replace("/", "--")
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _extract_params_b(data: dict) -> float | None:
    safetensors = data.get("safetensors", {})
    if safetensors:
        total = safetensors.get("total", 0)
        if total > 0:
            return round(total / 1e9, 1)
    model_id = data.get("id", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[bB]", model_id)
    if match:
        return float(match.group(1))
    return None


def _determine_quant(data: dict) -> str:
    tags = [t.lower() for t in data.get("tags", [])]
    if "gguf" in tags:
        return "Q4"
    for s in data.get("siblings", []):
        fname = s.get("rfilename", "").lower()
        if "q4" in fname:
            return "Q4"
        if "q8" in fname:
            return "Q8"
        if "fp16" in fname or "f16" in fname:
            return "FP16"
    return "FP16"


COST_TABLE = {
    (7, "Q4"): (0.03, 0.06),
    (7, "FP16"): (0.05, 0.10),
    (13, "Q4"): (0.05, 0.10),
    (13, "FP16"): (0.08, 0.16),
    (27, "Q4"): (0.08, 0.16),
    (27, "FP16"): (0.15, 0.30),
    (70, "Q4"): (0.20, 0.40),
    (70, "FP16"): (0.40, 0.80),
}


def _estimate_cost(params_b: float, quant: str) -> tuple[float, float]:
    closest = min(COST_TABLE.keys(), key=lambda k: abs(k[0] - params_b) + (0 if k[1] == quant else 5))
    return COST_TABLE[closest]


@router.post("/models/add-from-hf", response_model=ModelResponse)
async def add_model_from_hf(
    request: AddFromHfRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    hf_repo = request.hf_repo.strip()

    existing = await db.execute(select(LlmModel).where(LlmModel.hf_repo == hf_repo))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Model already exists")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"https://huggingface.co/api/models/{hf_repo}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Model not found on HuggingFace")
        resp.raise_for_status()
        data = resp.json()

    params_b = _extract_params_b(data)
    if params_b is None:
        raise HTTPException(status_code=400, detail="Could not determine model size. Add manually with params_b.")

    quant = _determine_quant(data)
    profile = resolve_deploy_profile(data, params_b=params_b, quantization=quant)
    gpu_type = profile["gpu_type"]
    gpu_count = profile["gpu_count"]
    cost_input, cost_output = _estimate_cost(params_b, quant)
    slug = _slugify(hf_repo)

    existing_slug = await db.execute(select(LlmModel).where(LlmModel.slug == slug))
    if existing_slug.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Model slug already exists")

    model = LlmModel(
        slug=slug,
        display_name=hf_repo.split("/")[-1],
        hf_repo=hf_repo,
        params_b=params_b,
        quantization=quant,
        gpu_type=gpu_type,
        gpu_count=gpu_count,
        max_context_length=profile["target_context"],
        cost_per_1m_input=cost_input,
        cost_per_1m_output=cost_output,
        description=data.get("cardData", {}).get("description") if data.get("cardData") else None,
        hf_downloads=data.get("downloads"),
        hf_likes=data.get("likes"),
        provider_override=normalize_provider_override(request.provider_override),
        provider_config=request.provider_config,
        status="pending",
        provider_status="pending",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return await _to_model_response(model, db)


@router.patch("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: uuid.UUID,
    request: UpdateModelRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    updates = request.model_dump(exclude_unset=True)
    if "provider_override" in updates:
        updates["provider_override"] = normalize_provider_override(updates["provider_override"])

    for field, value in updates.items():
        setattr(model, field, value)

    await db.commit()
    await db.refresh(model)
    return await _to_model_response(model, db)


async def _fetch_metadata(hf_repo: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"https://huggingface.co/api/models/{hf_repo}")
        resp.raise_for_status()
        return resp.json()


async def _deploy_runpod_model(model: LlmModel, profile: dict, db: AsyncSession) -> tuple[str | None, str | None]:
    result = await create_endpoint(
        name=f"unch-{model.slug}",
        gpu_type=profile["gpu_type"],
        docker_image=profile["docker_image"],
        model_name=model.hf_repo,
        params_b=float(model.params_b or 0),
        max_model_len=profile["target_context"],
        gpu_count=profile["gpu_count"],
        tool_parser=profile["tool_parser"],
        reasoning_parser=profile.get("reasoning_parser"),
        generation_config_mode=profile["generation_config_mode"],
        default_temperature=profile["default_temperature"],
        runtime_args=profile["runtime_args"],
        enforce_eager=profile.get("enforce_eager", False),
        gpu_memory_utilization=profile.get("gpu_memory_utilization"),
        runpod_init_timeout=profile.get("runpod_init_timeout"),
        execution_timeout_ms=profile.get("execution_timeout_ms"),
        db=db,
    )
    endpoint_data = result.get("data", {}).get("saveEndpoint", {})
    endpoint_id = endpoint_data.get("id")
    return endpoint_id, endpoint_id


async def _deploy_modal_model(model: LlmModel, profile: dict, db: AsyncSession) -> tuple[str | None, str | None, dict | None, str | None]:
    settings = await get_or_create_app_settings(db)
    result = await deploy_modal_model(model, profile, default_image=settings.modal_default_image)
    return None, result.get("deployment_ref"), result.get("provider_config"), result.get("provider_status")


@router.post("/models/{model_id}/deploy", response_model=DeployModelResponse)
async def deploy_model(
    model_id: uuid.UUID,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if model.status not in ("pending", "inactive"):
        raise HTTPException(status_code=400, detail=f"Cannot deploy model in '{model.status}' status")

    model.status = "deploying"
    model.provider_status = "deploying"
    await db.commit()

    try:
        metadata = await _fetch_metadata(model.hf_repo)
        profile = resolve_deploy_profile(metadata, params_b=float(model.params_b or 0), quantization=model.quantization)
        provider = await resolve_model_provider(model, db)
        if provider == MODAL and not modal_supports_runtime(profile):
            raise HTTPException(status_code=400, detail="Modal v1 supports only vLLM families; GGUF must stay on RunPod")

        model.gpu_type = profile["gpu_type"]
        model.gpu_count = profile["gpu_count"]
        model.max_context_length = profile["target_context"]

        if provider == MODAL:
            endpoint_id, deployment_ref, provider_config, provider_status = await _deploy_modal_model(model, profile, db)
            model.runpod_endpoint_id = None
            model.deployment_ref = deployment_ref
            model.provider_config = provider_config
            model.provider_status = provider_status or "provisioning"
            model.status = "active" if model.provider_status == "active" else "inactive"
        else:
            endpoint_id, deployment_ref = await _deploy_runpod_model(model, profile, db)
            model.runpod_endpoint_id = endpoint_id
            model.deployment_ref = deployment_ref
            model.provider_status = "active"
            model.status = "active"
    except HTTPException:
        model.status = "inactive"
        model.provider_status = "inactive"
        await db.commit()
        raise
    except Exception as e:
        model.status = "inactive"
        model.provider_status = "inactive"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")

    await db.commit()
    detail = "Model deployed" if model.status == "active" else "Provider scaffold prepared; model remains inactive until runtime is implemented"
    return DeployModelResponse(
        detail=detail,
        provider=await resolve_model_provider(model, db),
        endpoint_id=model.runpod_endpoint_id,
        deployment_ref=model.deployment_ref,
    )


@router.post("/models/{model_id}/redeploy", response_model=RedeployModelResponse)
async def redeploy_model(
    model_id: uuid.UUID,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    provider = await resolve_model_provider(model, db)
    model.status = "deploying"
    model.provider_status = "deploying"
    await db.commit()

    try:
        metadata = await _fetch_metadata(model.hf_repo)
        profile = resolve_deploy_profile(metadata, params_b=float(model.params_b or 0), quantization=model.quantization)
        if provider == MODAL and not modal_supports_runtime(profile):
            raise HTTPException(status_code=400, detail="Modal v1 supports only vLLM families; GGUF must stay on RunPod")

        model.gpu_type = profile["gpu_type"]
        model.gpu_count = profile["gpu_count"]
        model.max_context_length = profile["target_context"]

        if provider == RUNPOD and model.runpod_endpoint_id:
            await delete_endpoint(model.runpod_endpoint_id)
            model.runpod_endpoint_id = None
            await db.commit()

        if provider == MODAL:
            result = await redeploy_modal_model(model, profile)
            model.runpod_endpoint_id = None
            model.deployment_ref = result.get("deployment_ref")
            model.provider_config = result.get("provider_config")
            model.provider_status = result.get("provider_status", "provisioning")
            model.status = "active" if model.provider_status == "active" else "inactive"
        else:
            endpoint_id, deployment_ref = await _deploy_runpod_model(model, profile, db)
            model.runpod_endpoint_id = endpoint_id
            model.deployment_ref = deployment_ref
            model.provider_status = "active"
            model.status = "active"
    except HTTPException:
        model.status = "inactive"
        model.provider_status = "inactive"
        await db.commit()
        raise
    except Exception as e:
        model.status = "inactive"
        model.provider_status = "inactive"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")

    await db.commit()
    detail = "Model redeployed" if model.status == "active" else "Provider scaffold updated; model remains inactive until runtime is implemented"
    return RedeployModelResponse(
        detail=detail,
        provider=provider,
        endpoint_id=model.runpod_endpoint_id,
        deployment_ref=model.deployment_ref,
    )


async def _delete_endpoint_background(endpoint_id: str) -> None:
    try:
        await delete_endpoint(endpoint_id)
    except Exception as exc:
        logger.warning("Background delete_endpoint(%s) failed: %s", endpoint_id, exc)


@router.post("/models/{model_id}/status", response_model=UpdateModelStatusResponse)
async def update_model_status(
    model_id: uuid.UUID,
    request: UpdateModelStatusRequest,
    background_tasks: BackgroundTasks,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    provider = await resolve_model_provider(model, db)
    pending_endpoint_delete: str | None = None

    if request.status == "inactive":
        if provider == RUNPOD and model.runpod_endpoint_id:
            pending_endpoint_delete = model.runpod_endpoint_id
            model.runpod_endpoint_id = None
        elif provider == MODAL:
            result = await disable_modal_model(model)
            model.deployment_ref = result.get("deployment_ref")
            model.provider_config = result.get("provider_config")
            model.provider_status = result.get("provider_status", "inactive")

    model.status = request.status
    if request.status != "inactive":
        model.provider_status = request.status
    await db.commit()

    if pending_endpoint_delete:
        background_tasks.add_task(_delete_endpoint_background, pending_endpoint_delete)

    return UpdateModelStatusResponse(
        detail=f"Model status updated to {request.status}",
        provider=provider,
        deployment_ref=model.deployment_ref,
        endpoint_id=model.runpod_endpoint_id,
    )


@router.get("/discovery/summary", response_model=DiscoverySummaryResponse)
async def discovery_summary(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).order_by(LlmModel.created_at.desc()))
    models = result.scalars().all()
    settings = await get_or_create_app_settings(db)

    qwen3_rows: list[ModelOptionResponse] = []
    gpt_oss_rows: list[ModelOptionResponse] = []

    for model in models:
        metadata = {"id": model.hf_repo, "tags": [], "cardData": {}}
        profile = resolve_deploy_profile(metadata, params_b=float(model.params_b or 0), quantization=model.quantization)
        row = ModelOptionResponse(
            slug=model.slug,
            hf_repo=model.hf_repo,
            provider_override=model.provider_override,
            effective_provider=await resolve_model_provider(model, db),
            runpod_endpoint_id=model.runpod_endpoint_id,
            deployment_ref=model.deployment_ref,
            family=profile["family"],
            docker_image=profile.get("docker_image") or settings.runpod_default_image,
            tool_parser=profile.get("tool_parser"),
            reasoning_parser=profile.get("reasoning_parser"),
            gpu_count=model.gpu_count,
            gpu_type=model.gpu_type,
            max_context_length=model.max_context_length,
            expected_status_behavior="RunPod status/warm/terminate/queue semantics preserved for runpod models; Modal remains scaffold/provisioning path.",
            known_good_smoke_path="POST /v1/chat/completions + GET /v1/models/{slug}/status",
        )
        if profile["family"].startswith("qwen3"):
            qwen3_rows.append(row)
        if profile["family"] == "gpt_oss":
            gpt_oss_rows.append(row)

    image_inventory = ImageInventoryResponse(
        images=[
            ImageInventoryItem(
                image="runpod/worker-v1-vllm:v2.14.0",
                usages=[
                    "backend/app/services/runpod_service.py",
                    "scout/scout/gpu_selector.py",
                ],
                source_of_truth_in_repo=False,
                notes="Repo references external image tags, but no worker Dockerfile/source found here.",
            ),
            ImageInventoryItem(
                image="may4vfx/worker-llamacpp:latest",
                usages=["backend/app/services/runpod_service.py", "backend/app/services/deploy_profile_service.py"],
                source_of_truth_in_repo=False,
                notes="Referenced as external GGUF worker image; no Dockerfile found in this repo.",
            ),
            ImageInventoryItem(
                image="vllm/vllm-openai:v0.11.2",
                usages=["scout/scout/gpu_selector.py", "backend/app/services/runpod_service.py"],
                source_of_truth_in_repo=False,
                notes="Referenced vendor image, not repo-owned source-of-truth.",
            ),
        ],
        source_of_truth_found=False,
        notes=[
            "Current repo contains image references and runtime assumptions, but not the worker Dockerfile/source-of-truth.",
            "This supports building a repo-owned Modal multimodel runtime image instead of assuming reusable existing workers.",
        ],
    )

    return DiscoverySummaryResponse(
        canaries=CanaryInventoryResponse(
            qwen3=qwen3_rows,
            gpt_oss=gpt_oss_rows,
            notes=[
                "Repo code confirms family-level Qwen3/GPT-OSS runtime behavior, but not a single authoritative production slug unless already stored in llm_models.",
                "Use explicit provider_override=runpod for existing active models during migration/backfill.",
            ],
        ),
        images=image_inventory,
    )
