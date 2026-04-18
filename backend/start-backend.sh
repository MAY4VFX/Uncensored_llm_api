#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS_ON_START:-0}" = "1" ]; then
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
