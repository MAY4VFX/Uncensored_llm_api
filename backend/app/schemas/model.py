import uuid
from datetime import datetime

from pydantic import BaseModel


class ProviderCapabilitiesResponse(BaseModel):
    supports_vllm: bool
    supports_gguf: bool
    supports_keep_warm: bool
    supports_explicit_warm: bool
    supports_terminate: bool
    supports_queue_status: bool
    supports_multigpu: bool


class ModelResponse(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    hf_repo: str
    params_b: float
    quantization: str
    gpu_type: str
    gpu_count: int = 1
    max_context_length: int
    status: str
    provider_status: str | None = None
    provider_override: str | None = None
    effective_provider: str
    provider_config: dict | None = None
    deployment_ref: str | None = None
    runpod_endpoint_id: str | None = None
    cost_per_1m_input: float
    cost_per_1m_output: float
    description: str | None
    system_prompt: str | None = None
    hf_downloads: int | None = None
    hf_likes: int | None = None
    capabilities: ProviderCapabilitiesResponse
    created_at: datetime

    model_config = {"from_attributes": True}


class AppSettingsResponse(BaseModel):
    default_provider: str
    modal_default_image: str | None = None
    runpod_default_image: str | None = None
    provider_flags: dict | None = None
    supported_providers: list[str]


class UpdateAppSettingsRequest(BaseModel):
    default_provider: str | None = None
    modal_default_image: str | None = None
    runpod_default_image: str | None = None
    provider_flags: dict | None = None


class CreateModelRequest(BaseModel):
    slug: str
    display_name: str
    hf_repo: str
    params_b: float
    quantization: str = "Q4"
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    description: str | None = None
    provider_override: str | None = None
    provider_config: dict | None = None


class AddFromHfRequest(BaseModel):
    hf_repo: str
    provider_override: str | None = None
    provider_config: dict | None = None


class UpdateModelRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    gpu_type: str | None = None
    gpu_count: int | None = None
    max_context_length: int | None = None
    system_prompt: str | None = None
    provider_override: str | None = None
    provider_config: dict | None = None
    deployment_ref: str | None = None
    provider_status: str | None = None


class UpdateModelStatusRequest(BaseModel):
    status: str


class DeployModelResponse(BaseModel):
    detail: str
    provider: str
    endpoint_id: str | None = None
    deployment_ref: str | None = None


class RedeployModelResponse(BaseModel):
    detail: str
    provider: str
    endpoint_id: str | None = None
    deployment_ref: str | None = None


class UpdateModelStatusResponse(BaseModel):
    detail: str
    provider: str
    deployment_ref: str | None = None
    endpoint_id: str | None = None


class ResolveProviderRequest(BaseModel):
    provider_override: str | None = None
    provider_config: dict | None = None
    hf_repo: str
    params_b: float
    quantization: str = "Q4"


class ResolveProviderResponse(BaseModel):
    effective_provider: str
    capabilities: ProviderCapabilitiesResponse
    family: str
    warnings: list[str]
    can_deploy: bool
    profile: dict


class AvailableProviderResponse(BaseModel):
    id: str
    label: str
    capabilities: ProviderCapabilitiesResponse


class AvailableProvidersResponse(BaseModel):
    default_provider: str
    providers: list[AvailableProviderResponse]


class ModelOptionResponse(BaseModel):
    slug: str
    hf_repo: str
    provider_override: str | None = None
    effective_provider: str
    runpod_endpoint_id: str | None = None
    deployment_ref: str | None = None
    family: str | None = None
    docker_image: str | None = None
    tool_parser: str | None = None
    reasoning_parser: str | None = None
    gpu_count: int
    gpu_type: str
    max_context_length: int
    expected_status_behavior: str
    known_good_smoke_path: str


class CanaryInventoryResponse(BaseModel):
    qwen3: list[ModelOptionResponse]
    gpt_oss: list[ModelOptionResponse]
    notes: list[str]


class ImageInventoryItem(BaseModel):
    image: str
    usages: list[str]
    source_of_truth_in_repo: bool
    notes: str | None = None


class ImageInventoryResponse(BaseModel):
    images: list[ImageInventoryItem]
    source_of_truth_found: bool
    notes: list[str]


class DiscoverySummaryResponse(BaseModel):
    canaries: CanaryInventoryResponse
    images: ImageInventoryResponse
