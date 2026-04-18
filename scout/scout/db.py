from sqlalchemy import JSON, Column, DateTime, Enum, Float, Integer, Numeric, String, Text, create_engine, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from scout.config import settings

engine = create_engine(settings.database_url_sync, echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class LlmModel(Base):
    __tablename__ = "llm_models"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    slug = Column(String(200), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    hf_repo = Column(String(300), nullable=False)
    params_b = Column(Float, nullable=False)
    quantization = Column(String(10), nullable=False, server_default="Q4")
    gpu_type = Column(String(50), nullable=False)
    gpu_count = Column(Integer, nullable=False, server_default="1")
    provider_override = Column(String(20), nullable=True)
    provider_config = Column(JSON, nullable=True)
    deployment_ref = Column(String(255), nullable=True)
    runpod_endpoint_id = Column(String(100), nullable=True)
    provider_status = Column(String(50), nullable=True)
    status = Column(
        Enum("pending", "deploying", "active", "inactive", name="model_status", create_type=False),
        nullable=False,
        server_default="pending",
    )
    max_context_length = Column(Integer, nullable=False, server_default="4096")
    cost_per_1m_input = Column(Numeric(10, 4), nullable=False, server_default="0")
    cost_per_1m_output = Column(Numeric(10, 4), nullable=False, server_default="0")
    gpu_hourly_cost = Column(Numeric(10, 4), nullable=False, server_default="0")
    keep_warm_price = Column(Numeric(10, 4), nullable=False, server_default="0")
    margin_multiplier = Column(Float, nullable=False, server_default="1.5")
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    hf_downloads = Column(Integer, nullable=True)
    hf_likes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    default_provider = Column(String(20), nullable=False, server_default="modal")


def get_session() -> Session:
    return SessionLocal()


def get_default_provider(session: Session) -> str:
    settings = session.query(AppSettings).filter(AppSettings.id == 1).first()
    if not settings or settings.default_provider not in {"runpod", "modal"}:
        return "modal"
    return settings.default_provider


def model_exists(session: Session, hf_repo: str) -> bool:
    model = session.query(LlmModel).filter(LlmModel.hf_repo == hf_repo).first()
    if model:
        if model.provider_status is None:
            model.provider_status = model.status
            session.commit()
        if model.deployment_ref is None and model.runpod_endpoint_id:
            model.deployment_ref = model.runpod_endpoint_id
            session.commit()
        return True
    return False


def insert_model(session: Session, model_data: dict) -> LlmModel:
    payload = dict(model_data)
    payload.setdefault("provider_config", None)
    payload.setdefault("deployment_ref", None)
    payload.setdefault("provider_status", payload.get("status", "pending"))
    payload.setdefault("gpu_hourly_cost", 0)
    payload.setdefault("keep_warm_price", 0)
    payload.setdefault("margin_multiplier", 1.5)
    payload.setdefault("system_prompt", None)

    effective_provider = get_default_provider(session)
    payload.setdefault("provider_override", None if effective_provider == "modal" else effective_provider)

    model = LlmModel(**payload)
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def update_model_status(session: Session, model_id, status: str, endpoint_id: str = None):
    model = session.query(LlmModel).filter(LlmModel.id == model_id).first()
    if model:
        model.status = status
        model.provider_status = status
        if endpoint_id:
            model.runpod_endpoint_id = endpoint_id
            model.deployment_ref = endpoint_id
        session.commit()


def update_hf_stats(session: Session, hf_repo: str, downloads: int, likes: int):
    model = session.query(LlmModel).filter(LlmModel.hf_repo == hf_repo).first()
    if model:
        model.hf_downloads = downloads
        model.hf_likes = likes
        if model.provider_status is None:
            model.provider_status = model.status
        if model.deployment_ref is None and model.runpod_endpoint_id:
            model.deployment_ref = model.runpod_endpoint_id
        session.commit()


def should_auto_deploy_runpod(session: Session, provider_override: str | None) -> bool:
    effective_provider = provider_override or get_default_provider(session)
    return effective_provider == "runpod"
