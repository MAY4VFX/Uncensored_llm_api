from datetime import datetime

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="modal")
    modal_default_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runpod_default_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
