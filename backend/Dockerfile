# syntax=docker/dockerfile:1
# ============================================================
# STAGE 1 — Dependencias y entorno Python (uv)
# ============================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN pip install --no-cache-dir "uv==0.12.10"

WORKDIR /build

# Dependencias primero (aprovecha la caché de capas mientras no cambie el lock).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Código fuente y proyecto.
COPY app ./app
RUN uv sync --frozen --no-dev

# ============================================================
# STAGE 2 — Runtime (slim, usuario no-root, sin herramientas dev)
# ============================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=UTC

# Usuario no-root.
RUN groupadd --system --gid 1001 alucard \
    && useradd --system --uid 1001 --gid 1001 --shell /usr/sbin/nologin alucard

WORKDIR /app

# Entorno virtual construido arriba (interp. base idéntico en ambas etapas).
COPY --from=builder /build/.venv ./.venv
COPY --chown=alucard:alucard app ./app

# Directorios de datos persistentes (named volume hereda este propietario) y
# punto de montaje del volcado (solo lectura).
RUN mkdir -p /data /dump && chown alucard:alucard /data /dump

COPY --chown=alucard:alucard entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

USER alucard
EXPOSE 7331

ENTRYPOINT ["/app/entrypoint.sh"]
