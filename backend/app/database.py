from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Streaming chat handlers hold the DB session for the entire response
# (FastAPI keeps the Depends generator alive until StreamingResponse ends).
# A cold-start RunPod worker can take 2-3 minutes per request, so the
# default 5+10 pool is exhausted quickly under any concurrency.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=50,
    max_overflow=100,
    pool_timeout=60,
    pool_recycle=1800,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
