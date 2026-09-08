#!/bin/sh
# Entrypoint del contenedor backend:
#  1) Crea el esquema e ingiere el volcado MEGA si la BD está vacía (idempotente).
#  2) Arranca la API.
set -eu

: "${ALUCARD_DUMP_PATH:=/dump/mega_cuenta_contenido_MEGAcmd.txt}"
: "${ALUCARD_DB_PATH:=/data/alucard.db}"
: "${ALUCARD_API_PORT:=7331}"

echo "[entrypoint] dump=${ALUCARD_DUMP_PATH}"
echo "[entrypoint] db=${ALUCARD_DB_PATH}"

if [ -f "${ALUCARD_DUMP_PATH}" ]; then
    echo "[entrypoint] verificando/creando snapshot inicial…"
    python -m app.ingest --dump "${ALUCARD_DUMP_PATH}" --db "${ALUCARD_DB_PATH}" --if-empty
else
    echo "[entrypoint] aviso: volcado no montado (${ALUCARD_DUMP_PATH}); la API arranca sin datos."
    python -c "from app.config import settings; from app.db import create_schema; create_schema(settings.resolved_database_url)"
fi

echo "[entrypoint] arrancando API en 0.0.0.0:${ALUCARD_API_PORT}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${ALUCARD_API_PORT}"
