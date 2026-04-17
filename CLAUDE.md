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

## Tool calling: что мы выучили на Qwen3-Coder

Эта секция фиксирует root causes отладки tool-calling под opencode/OpenClaude — чтобы при разворачивании следующей модели не наступать заново.

### Все 4 разных слоя одной проблемы

1. **Wrong vLLM tool parser.** Qwen3-Coder обучен на нативном XML
   `<function=name><parameter=...>...</parameter></function>` — для него
   нужен парсер **`qwen3_coder`**. Универсальный `qwen3_xml` (wrapper
   `<tool_call>{...}</tool_call>`) молча теряет tool_calls под длинными
   агентскими промптами. См. opencode #1809, vLLM/opencode #16488.

2. **Стрим стирал tool_calls.** Старая версия `proxy_chat_completion_stream`
   извлекала из vLLM SSE только `delta.content` через `_extract_text` —
   `tool_calls` форвардить было нечем. Non-stream работал, поэтому баг
   маскировался под «модель тупит», хотя по факту это был наш бекенд.

3. **vLLM `qwen3_coder` в стриме шлёт arguments как JSON-encoded строку**
   (двойное кодирование): `"\"{\\\"filePath\\\":\\\"...\\\"}\""` вместо
   `{"filePath":"..."}`. opencode zod валидация → `expected object,
   received string`.

4. **vLLM `qwen3_coder` в стриме шлёт *накопленные* arguments в каждом
   chunk-е** (не инкременты). Клиент конкатенирует по OpenAI спеке →
   получает `{"command":"a"{"command":"a","description":"..."}` →
   `Invalid tool parameters` или `command missing`.

### Где это исправлено в коде

- `backend/app/services/deploy_profile_service.py` — qwen3_coder family
  деплоится с `tool_parser="qwen3_coder"`.
- `backend/app/services/runpod_service.py` — `_parse_sse_chunks` /
  `_extract_chunks` форвардят полные дельты как `__CHUNK:<json>`,
  `_normalize_tool_call_arguments` распаковывает double-encoded args.
- `backend/app/services/proxy_service.py` — буферизирует tool_calls
  per `(choice_index, tool_index)`, накапливает cumulative→full,
  нормализует, эмитит **один валидный chunk** перед finish, на любой
  tool_call принудительно ставит `finish_reason="tool_calls"`.
- `scout/scout/deployer.py` — вторая точка деплоя, тоже использует
  `qwen3_coder` для qwen3-coder моделей (раньше хардкодил `qwen3_xml`).
- `backend/tests/test_streaming_openai_compat.py` — 9 регрессионных
  тестов на normalize, double-encoded, accumulated→incremental,
  finish_reason normalization, status events.
- `backend/app/database.py` — DB pool 50+100 + pool_pre_ping.
  Streaming-handlers держат session весь ответ (FastAPI Depends-generator
  жив до конца StreamingResponse), поэтому при cold start RunPod
  default 5+10 коннектов кончался → Cloudflare 521.

### Чек-лист для разворачивания новой модели

1. **Подобрать tool parser под семейство модели:**
   | Семейство | parser |
   |---|---|
   | Qwen3-Coder | `qwen3_coder` |
   | Qwen3 chat/general | `hermes` |
   | GLM-4.5 | `glm45` |
   | Llama-3 | `llama3_json` |
   | Mistral | `mistral` |

   Источник истины — model card + `vllm/entrypoints/openai/tool_parsers/`.
   Для fine-tuned (abliterated, uncensored) парсер наследуется от базы.

2. **Чат-темплейт должен совпадать с тренировочной разметкой.** Проверить
   `tokenizer_config.json` и `chat_template.jinja` в HF репо. При
   несовпадении — tool_calls осядут в `content` и парсер их не вытащит.

3. **Smoke test перед сдачей в прод (минимум):**
   - non-stream + 1 tool → `tool_calls` в ответе
   - stream + 1 tool → `tool_calls` в финальном chunk-е
   - stream + 10+ tools (как opencode/OpenClaude) → корректные `tool_calls`
   - stream + длинная история (40+ messages) → не теряются
   - `JSON.parse(arguments)` парсится в **object**, не в **string**

4. **GPU и контекст** — проверить `_safe_context_on_gpu` в
   `deploy_profile_service.py`. 30B MoE FP16 → H200_141GB, ~210k безопасно.
   70B+ → H200, контекст 32-65k.

### Главный урок

Все 4 баги с tool_calls — **разные слои одного root cause**: vLLM
qwen3_coder парсер ведёт себя нестандартно в streaming режиме.
**При подозрении на tool-call баг — first-thing-first сделать прямой
raw-stream к RunPod и посмотреть сырые `function.arguments`.** Это сразу
покажет: parser правильный? args инкрементальные? args не двойно-
закодированные? Без этого шага легко уйти в prompt-ablation и не найти
настоящую причину.
