import re
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_admin_user
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.model import AddFromHfRequest, CreateModelRequest, ModelResponse, UpdateModelStatusRequest
from app.services.runpod_service import create_endpoint, delete_endpoint

router = APIRouter(prefix="/admin", tags=["admin"])

GPU_MATRIX = {
    "RTX_4000_Ada_20GB": 8,
    "RTX_A5000_24GB": 24,
    "A100_80GB": 80,
    "H100_80GB": 80,
    "H200_141GB": 141,
}

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}


def select_gpu(params_b: float, quant: str) -> tuple[str, int]:
    """Select GPU type and count. Returns (gpu_type, gpu_count)."""
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    vram_needed = params_b * multiplier * 1.3
    for gpu_name, vram in GPU_MATRIX.items():
        if vram_needed <= vram:
            return gpu_name, 1
    # Need multi-GPU — use largest GPU type
    best_gpu = "H200_141GB"
    best_vram = GPU_MATRIX[best_gpu]
    gpu_count = max(1, -(-int(vram_needed) // best_vram))  # ceil division
    gpu_count = min(gpu_count, 8)  # RunPod max 8 GPUs
    return best_gpu, gpu_count


@router.get("/models", response_model=list[ModelResponse])
async def list_all_models(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LlmModel).order_by(LlmModel.created_at.desc()))
    return result.scalars().all()


@router.get("/models/pending", response_model=list[ModelResponse])
async def list_pending_models(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LlmModel).where(LlmModel.status == "pending").order_by(LlmModel.created_at.desc())
    )
    return result.scalars().all()


@router.post("/models", response_model=ModelResponse)
async def create_model(
    request: CreateModelRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    # Check slug uniqueness
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
        status="pending",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


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
    (7, "Q4"): (0.03, 0.06), (7, "FP16"): (0.05, 0.10),
    (13, "Q4"): (0.05, 0.10), (13, "FP16"): (0.08, 0.16),
    (27, "Q4"): (0.08, 0.16), (27, "FP16"): (0.15, 0.30),
    (70, "Q4"): (0.20, 0.40), (70, "FP16"): (0.40, 0.80),
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
    """Add a model by HuggingFace repo ID. Fetches metadata automatically."""
    hf_repo = request.hf_repo.strip()

    # Check if already exists
    existing = await db.execute(select(LlmModel).where(LlmModel.hf_repo == hf_repo))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Model already exists")

    # Fetch from HuggingFace API
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
    gpu_type, gpu_count = select_gpu(params_b, quant)
    cost_input, cost_output = _estimate_cost(params_b, quant)
    slug = _slugify(hf_repo)

    # Check slug uniqueness
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
        cost_per_1m_input=cost_input,
        cost_per_1m_output=cost_output,
        description=data.get("cardData", {}).get("description") if data.get("cardData") else None,
        hf_downloads=data.get("downloads"),
        hf_likes=data.get("likes"),
        status="pending",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.post("/models/{model_id}/deploy")
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
    await db.commit()

    try:
        result = await create_endpoint(
            name=f"unch-{model.slug}",
            gpu_type=model.gpu_type,
            model_name=model.hf_repo,
            params_b=float(model.params_b or 0),
            max_model_len=model.max_context_length or 4096,
            gpu_count=model.gpu_count or 1,
            db=db,
        )
        endpoint_data = result.get("data", {}).get("saveEndpoint", {})
        model.runpod_endpoint_id = endpoint_data.get("id")
        model.status = "active"
    except Exception as e:
        model.status = "inactive"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")

    await db.commit()
    return {"detail": "Model deployed", "endpoint_id": model.runpod_endpoint_id}


@router.post("/models/{model_id}/redeploy")
async def redeploy_model(
    model_id: uuid.UUID,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    model.status = "deploying"
    await db.commit()

    try:
        if model.runpod_endpoint_id:
            await delete_endpoint(model.runpod_endpoint_id)
            model.runpod_endpoint_id = None
            await db.commit()

        result = await create_endpoint(
            name=f"unch-{model.slug}",
            gpu_type=model.gpu_type,
            model_name=model.hf_repo,
            params_b=float(model.params_b or 0),
            max_model_len=model.max_context_length or 4096,
            gpu_count=model.gpu_count or 1,
            db=db,
        )
        endpoint_data = result.get("data", {}).get("saveEndpoint", {})
        model.runpod_endpoint_id = endpoint_data.get("id")
        model.status = "active"
    except Exception as e:
        model.status = "inactive"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")

    await db.commit()
    return {"detail": "Model redeployed", "endpoint_id": model.runpod_endpoint_id}


@router.post("/models/{model_id}/status")
async def update_model_status(
    model_id: uuid.UUID,
    request: UpdateModelStatusRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if request.status == "inactive" and model.runpod_endpoint_id:
        try:
            await delete_endpoint(model.runpod_endpoint_id)
        except Exception:
            pass
        model.runpod_endpoint_id = None

    model.status = request.status
    await db.commit()
    return {"detail": f"Model status updated to {request.status}"}
