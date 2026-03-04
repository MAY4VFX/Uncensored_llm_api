# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is This

UnchainedAPI — платформа для доступа к нецензурированным (uncensored/abliterated) LLM-моделям через OpenAI-совместимый API. Три сервиса в монорепо: FastAPI бекенд, Next.js фронтенд, Scout-агент.

## Commands

### Local Development (Docker Compose)

```bash
# Поднять все сервисы
docker-compose up -d

# Миграции БД
docker-compose exec backend alembic upgrade head

# Создать новую миграцию
docker-compose exec backend alembic revision --autogenerate -m "описание"
```

### Backend (Python 3.12, FastAPI)

```bash
cd backend
pip install -r requirements.txt

# Запуск dev-сервера
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Тесты (используют SQLite вместо PostgreSQL)
pip install pytest pytest-asyncio httpx aiosqlite
pytest tests/ -v
pytest tests/test_auth.py -v          # один файл
pytest tests/test_auth.py::test_name  # один тест
```

### Frontend (Next.js 14, TypeScript, Tailwind CSS 3)

```bash
cd frontend
npm install
npm run dev    # :3000
npm run build
npm run lint
```

### Scout Agent

```bash
cd scout
pip install -r requirements.txt
python -m scout.main
```

## Architecture

```
User → Next.js (:3000) → FastAPI (:8000) → RunPod vLLM Endpoints
                              ↕
                    PostgreSQL (:5432) + Redis (:6379)

Scout Agent (cron) → HuggingFace Hub → RunPod GraphQL → PostgreSQL
```

**Backend** (`backend/app/`): FastAPI gateway. Точка входа — `main.py`. Конфигурация через pydantic-settings (`config.py`). Async SQLAlchemy + asyncpg (`database.py`).

**Frontend** (`frontend/src/`): Next.js 14 App Router. JWT хранится в localStorage (`lib/auth.ts`, ключ `unchained_token`). Все API-вызовы через обёртку в `lib/api.ts`. Тёмная тема по умолчанию.

**Scout** (`scout/scout/`): Авто-обнаружение моделей с HuggingFace. Использует **синхронный** SQLAlchemy (psycopg2), в отличие от бекенда. Анализ model cards через Claude API (claude-haiku-4-5). Расписание через APScheduler.

## Key Patterns

**Двойная аутентификация** (`dependencies.py`):
- JWT Bearer — для дашборда/админки (`get_current_user`, `get_admin_user`)
- API Key формата `sk-unch-<64hex>` — для LLM вызовов (`verify_api_key`). Хранятся только SHA-256 хэши, raw key возвращается однократно при создании.

**Rate Limiting** (`middleware/rate_limiter.py`): Redis sorted sets, sliding window 1 мин. Лимиты по тиру: free=20, starter=60, pro=120, business=300 req/min.

**RunPod Proxy** (`services/proxy.py`):
- Non-streaming: POST `/runsync` → синхронный ответ
- Streaming: POST `/run` → poll `/stream/{job_id}` каждые 0.5s → SSE клиенту

**Подсчёт токенов**: tiktoken (cl100k_base), +4 токена overhead на сообщение.

**Кредитная система** (`services/credits.py`): `users.credits` (Numeric 12,6), проверка и списание перед каждым запросом.

**Биллинг**: Paddle webhooks. Пакеты кредитов и подписки по тирам.

**RunPod деплой** (`scout/deployer.py`): через GraphQL API (`saveEndpoint`), не REST.

## Database

PostgreSQL 16. Миграции через Alembic (`backend/alembic/`). Таблицы: `users`, `api_keys`, `llm_models`, `usage_logs`. Enum типы: `user_tier` (free/starter/pro/business), `model_status` (pending/deploying/active/inactive).

## Deployment

Деплой через Dokploy — пуш в ветку автоматически запускает деплой. Docker-образы собираются через Dokploy, **не вручную через docker-compose build**.

## Ports

| Сервис | Порт |
|--------|------|
| Backend (FastAPI) | 8000 |
| Frontend (Next.js) | 3000 |
| PostgreSQL | 5432 |
| Redis | 6379 |
