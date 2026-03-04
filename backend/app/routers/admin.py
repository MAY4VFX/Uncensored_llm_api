import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_admin_user
from app.models.llm_model import LlmModel
from app.models.user import User
from app.schemas.model import CreateModelRequest, ModelResponse, UpdateModelStatusRequest
from app.services.runpod_service import create_endpoint, delete_endpoint

router = APIRouter(prefix="/admin", tags=["admin"])

GPU_MATRIX = {
    "RTX_4000_Ada_20GB": 8,
    "RTX_A4500_20GB": 16,
    "RTX_A5000_24GB": 24,
    "A100_40GB": 40,
    "A100_80GB": 80,
}

QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}


def select_gpu(params_b: float, quant: str) -> str:
    multiplier = QUANT_MULTIPLIERS.get(quant, 1.0)
    vram_needed = params_b * multiplier * 1.3
    for gpu_name, vram in GPU_MATRIX.items():
        if vram_needed <= vram:
            return gpu_name
    return "A100_80GB"


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

    gpu_type = select_gpu(request.params_b, request.quantization)
    model = LlmModel(
        slug=request.slug,
        display_name=request.display_name,
        hf_repo=request.hf_repo,
        params_b=request.params_b,
        quantization=request.quantization,
        gpu_type=gpu_type,
        cost_per_1m_input=request.cost_per_1m_input,
        cost_per_1m_output=request.cost_per_1m_output,
        description=request.description,
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
