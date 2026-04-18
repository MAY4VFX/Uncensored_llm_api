# Dokploy split deploy

Этот каталог — source of truth для перехода от одного compose stack к отдельным Dokploy apps.

## Target services

- `backend`
  - build context: `backend/`
  - dockerfile: `backend/Dockerfile`
  - port: `8000`
  - healthcheck: `GET /health`
  - release step: `alembic upgrade head`
- `frontend`
  - build context: `frontend/`
  - dockerfile: `frontend/Dockerfile`
  - port: `3000`
  - healthcheck: `GET /`
  - required env: `BACKEND_URL`
- `scout`
  - build context: `scout/`
  - dockerfile: `scout/Dockerfile`
  - worker only, без public domain

## External infrastructure

- `postgres`
- `redis`

Они должны жить как отдельные Dokploy services, а не внутри app compose.

## Environment files

- `backend.env.example`
- `frontend.env.example`
- `scout.env.example`

Это шаблоны для Dokploy env, не для локального запуска.

## Backend rollout rule

`backend` нельзя переключать в прод без migration step:

```sh
alembic upgrade head
```

По умолчанию контейнер НЕ запускает миграции автоматически. Если нужен временный startup-runner, можно выставить:

```sh
RUN_MIGRATIONS_ON_START=1
```

Но рекомендуемый путь — отдельный release/predeploy step в Dokploy.

## Frontend runtime rule

`frontend` не должен полагаться на compose hostname `http://backend:8000` вне compose stack.

Для split deploy обязательно задавать:

```sh
BACKEND_URL=http://<backend-service-host>:8000
```

или backend public/internal Dokploy URL.

## Scout runtime rule

`scout` остаётся discovery-first worker.

- RunPod auto-deploy разрешён только для effective provider = `runpod`
- Modal-target модели `scout` не деплоит напрямую, только пишет metadata и пропускает direct deploy

## Modal architecture

Modal — внешний provider.

Dokploy хостит только control-plane сервисы этого репозитория:
- backend
- frontend
- scout

Реальный Modal deploy/status/inference lifecycle должен жить в backend, а не в Dokploy service layer.
