# UnchainedAPI

API platform for uncensored/abliterated LLM models with OpenAI-compatible endpoints. Automatic model discovery from HuggingFace, serverless GPU inference via RunPod, pay-per-token pricing.

## Architecture

```
VPS (Dokploy)                          RunPod Serverless
├── FastAPI (API Gateway)    ──────►   ├── vLLM Endpoint (model-1)
├── Next.js (Frontend)                 ├── vLLM Endpoint (model-2)
├── PostgreSQL                         └── vLLM Endpoint (model-N)
├── Redis
└── Scout Agent (cron)
```

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Start all services
docker-compose up -d

# 3. Run migrations
docker-compose exec backend alembic upgrade head

# 4. Access
# API:      http://localhost:8000
# Frontend: http://localhost:3000
# Docs:     http://localhost:3000/docs
```

## API Usage

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-unch-your-key-here",
    base_url="https://api.unchained.ai/v1"
)

response = client.chat.completions.create(
    model="your-model-slug",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## Project Structure

- `backend/` — FastAPI API Gateway (auth, proxy, usage tracking, billing)
- `frontend/` — Next.js dashboard (model catalog, API keys, usage, docs)
- `scout/` — Model Scout Agent (auto-discovers models from HuggingFace)
- `docker-compose.yml` — Full stack deployment

## Stack

| Component | Technology |
|-----------|-----------|
| API Gateway | FastAPI + SQLAlchemy + Redis |
| Frontend | Next.js 14 + Tailwind CSS |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| GPU Inference | RunPod Serverless (vLLM) |
| Billing | Paddle |
| Deployment | Docker Compose / Dokploy |
