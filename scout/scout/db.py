from sqlalchemy import Column, DateTime, Enum, Float, Integer, Numeric, String, Text, create_engine, func
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
    runpod_endpoint_id = Column(String(100), nullable=True)
    status = Column(
        Enum("pending", "deploying", "active", "inactive", name="model_status", create_type=False),
        nullable=False,
        server_default="pending",
    )
    max_context_length = Column(Integer, nullable=False, server_default="4096")
    cost_per_1m_input = Column(Numeric(10, 4), nullable=False, server_default="0")
    cost_per_1m_output = Column(Numeric(10, 4), nullable=False, server_default="0")
    description = Column(Text, nullable=True)
    hf_downloads = Column(Integer, nullable=True)
    hf_likes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def get_session() -> Session:
    return SessionLocal()


def model_exists(session: Session, hf_repo: str) -> bool:
    return session.query(LlmModel).filter(LlmModel.hf_repo == hf_repo).first() is not None


def insert_model(session: Session, model_data: dict) -> LlmModel:
    model = LlmModel(**model_data)
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def update_model_status(session: Session, model_id, status: str, endpoint_id: str = None):
    model = session.query(LlmModel).filter(LlmModel.id == model_id).first()
    if model:
        model.status = status
        if endpoint_id:
            model.runpod_endpoint_id = endpoint_id
        session.commit()


def update_hf_stats(session: Session, hf_repo: str, downloads: int, likes: int):
    model = session.query(LlmModel).filter(LlmModel.hf_repo == hf_repo).first()
    if model:
        model.hf_downloads = downloads
        model.hf_likes = likes
        session.commit()
