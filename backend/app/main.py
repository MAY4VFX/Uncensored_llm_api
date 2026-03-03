from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.routers import admin, api_keys, auth, billing, chat, models, playground, usage


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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


@app.get("/health")
async def health():
    return {"status": "ok"}
