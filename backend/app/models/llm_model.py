import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LlmModel(Base):
    __tablename__ = "llm_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hf_repo: Mapped[str] = mapped_column(String(300), nullable=False)
    params_b: Mapped[float] = mapped_column(Float, nullable=False)
    quantization: Mapped[str] = mapped_column(String(10), nullable=False, default="Q4")
    gpu_type: Mapped[str] = mapped_column(String(50), nullable=False)
    runpod_endpoint_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "deploying", "active", "inactive", name="model_status"),
        nullable=False,
        default="pending",
    )
    max_context_length: Mapped[int] = mapped_column(nullable=False, default=4096)
    cost_per_1m_input: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0)
    cost_per_1m_output: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0)
    gpu_hourly_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0)
    keep_warm_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hf_downloads: Mapped[int | None] = mapped_column(nullable=True)
    hf_likes: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
