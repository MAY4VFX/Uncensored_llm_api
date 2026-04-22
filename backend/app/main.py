import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import async_session, engine
from app.routers import admin, api_keys, auth, billing, chat, keep_warm, models, playground, usage
from app.services.keep_warm_service import tick_billing
from app.services.modal_service import aclose_shared_client

logger = logging.getLogger(__name__)


async def _keep_warm_ticker():
    while True:
        await asyncio.sleep(60)
        try:
            async with async_session() as db:
                await tick_billing(db)
        except Exception:
            logger.exception("keep_warm ticker error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_keep_warm_ticker())
    yield
    task.cancel()
    await aclose_shared_client()
    await engine.dispose()


app = FastAPI(
    title="UnchainedAPI",
    description="API platform for uncensored LLM models — OpenAI-compatible endpoints",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(usage.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(playground.router)
app.include_router(keep_warm.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
