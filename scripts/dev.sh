#!/usr/bin/env bash
# Arranca backend + frontend en local.
# OJO: por convención se usan 7331 (API) y 7330 (web), como en proyecto-heredado.
# Si esos puertos ya están ocupados (p. ej. por otro scrob), cambia:
#   ALUCARD_BACKEND_PORT=7441 ALUCARD_FRONTEND_PORT=7440 ./scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${ALUCARD_BACKEND_PORT:-7331}"
FRONTEND_PORT="${ALUCARD_FRONTEND_PORT:-7330}"

# 1) Asegura BD ingerida (rápido si ya existe el snapshot más reciente).
if [ ! -f "$ROOT/data/alucard.db" ]; then
  echo "· Ingestando el volcado por primera vez…"
  (cd "$ROOT/backend" && uv run python -m app.ingest)
fi

echo "· Backend  → http://localhost:$BACKEND_PORT  (docs: /docs)"
(cd "$ROOT/backend" && exec uv run uvicorn app.main:app --port "$BACKEND_PORT") &
BACK_PID=$!

echo "· Frontend → http://localhost:$FRONTEND_PORT"
(cd "$ROOT/frontend" && PUBLIC_BACKEND_PORT="$BACKEND_PORT" exec pnpm dev --port "$FRONTEND_PORT") &
FRONT_PID=$!

trap 'kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true' EXIT INT TERM
wait
