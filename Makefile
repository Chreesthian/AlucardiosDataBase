# Makefile de AlucardiosDataBase
SHELL := /bin/bash

# El puerto del backend vive en `.env` (BACKEND_PORT=7441) y el Makefile no lo
# carga solo: se resuelve aquí para que `make retro-sync`, `retro-status` y
# `sync-status` apunten a donde escucha la API sin exportar nada a mano. Es la
# misma resolución que usa `scripts/volcado_retro.sh`.
BACKEND_PORT ?= $(shell grep -E '^BACKEND_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"'"'"' ')
BACKEND_PORT := $(if $(strip $(BACKEND_PORT)),$(strip $(BACKEND_PORT)),7331)
export BACKEND_PORT

.PHONY: help build up down ps logs restart dev test lint clean volcado novedades pre-vuelo rotacion \
	enrich enrich-retro enrich-campos enrich-retro-campos volcado-retro volcado-retro-cron \
	volcado-retro-cron-off volcado-retro-estado \
	retro-credenciales retro-status retro-sync

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

build: ## Construye las imágenes (backend + frontend)
	docker compose build

up: ## Levanta el stack (web :7330, api :7331)
	docker compose up -d --build

down: ## Detiene el stack
	docker compose down

ps: ## Estado de los servicios
	docker compose ps

logs: ## Logs de todos los servicios
	docker compose logs -f

restart: ## Reinicia el stack
	docker compose restart

dev: ## Arranque local sin docker (uv + pnpm)
	./scripts/dev.sh

test: ## Tests del backend (requiere uv)
	cd backend && uv run pytest

lint: ## Compilación/typecheck básicos
	cd backend && uv run python -m compileall -q app
	cd frontend && pnpm build

e2e: ## Auditoría end-to-end con Playwright (requiere stack arriba)
	cd e2e && pnpm install && pnpm exec playwright install chromium && pnpm test

audit: ## Despliegue limpio + auditoría interna/externa
	docker compose up -d --build
	cd e2e && pnpm install && pnpm exec playwright install chromium && pnpm test

enrich: ## Enriquece títulos con la ficha IGDB completa (GamesDb)
	docker compose exec -T backend /app/.venv/bin/python -m app.enrich

enrich-retro: ## Enriquece la colección RETRO con la ficha IGDB completa (SU BD)
	docker compose exec -T backend /app/.venv/bin/python -m app.enrich --db /data/retro.db --coleccion retro

enrich-campos: ## Pone al día nombre oficial/año y portadas SIN red (catálogo Switch)
	docker compose exec -T backend /app/.venv/bin/python -m app.enrich --campos

enrich-retro-campos: ## Pone al día nombre oficial/año y portadas SIN red (colección retro)
	docker compose exec -T backend /app/.venv/bin/python -m app.enrich --db /data/retro.db --coleccion retro --campos

volcado: ## Refresca el volcado canónico desde MEGA (requiere sesión MEGAcmd)
	cd backend && uv run python ../scripts/refrescar_volcado.py

volcado-auto: ## Refresca el volcado AHORA y aplica el escaneo (falla ruidoso)
	./scripts/autovolcado.sh

volcado-cron: ## Instala el refresco automático del volcado (cron cada 6 h)
	./scripts/autovolcado.sh --install-cron

volcado-cron-off: ## Quita el refresco automático del volcado
	./scripts/autovolcado.sh --remove-cron

volcado-estado: ## Último resultado del refresco automático del volcado
	./scripts/autovolcado.sh --estado

pre-vuelo: ## ¿La cuenta MEGA de la semana ve la biblioteca del volcado? (host, sin tocar el volcado)
	cd backend && uv run python ../scripts/verificar_rotacion.py

rotacion: ## Failover: deja la sesión en la cuenta del pool que SÍ ve la biblioteca
	cd backend && uv run python ../scripts/verificar_rotacion.py --elegir-cuenta

volcado-retro: ## Refresca el volcado de ROMs RETRO y escanea SU BD (host)
	./scripts/volcado_retro.sh

volcado-retro-cron: ## Instala el refresco automático del retro (cron cada 6 h)
	./scripts/volcado_retro.sh --install-cron

volcado-retro-cron-off: ## Quita el refresco automático del retro
	./scripts/volcado_retro.sh --remove-cron

volcado-retro-estado: ## Último resultado del refresco automático del retro
	./scripts/volcado_retro.sh --estado

retro-credenciales: ## Guarda la cuenta MEGA de la semana que ve las ROMs retro
	./scripts/volcado_retro.sh --set-cred

retro-status: ## Frescura y tamaño de la colección retro (API)
	@curl -s "http://127.0.0.1:$${BACKEND_PORT:-7331}/api/retro/status" | python3 -m json.tool

retro-sync: ## Escaneo manual del volcado retro en la API (su BD, no la de Switch)
	@curl -s -X POST "http://127.0.0.1:$${BACKEND_PORT:-7331}/api/retro/dump" -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool

credenciales: ## Guarda las credenciales MEGA de la semana (rotan semanalmente)
	./scripts/autovolcado.sh --set-cred

sync-status: ## Frescura del volcado y estado del vigía (API)
	@curl -s "http://127.0.0.1:$${BACKEND_PORT:-7331}/api/sync/status" | python3 -m json.tool

sync: ## Escaneo incremental (añade/borra por diff, sin reconstruir) + export
	docker compose exec -T backend /app/.venv/bin/python -m app.sync --dump /dump/mega_cuenta_contenido_MEGAcmd.txt --export

novedades: ## Novedades registradas (juegos nuevos y contenido nuevo)
	docker compose exec -T backend /app/.venv/bin/python -m app.novedades

export: ## Exporta la biblioteca completa a data/biblioteca.json
	docker compose exec -T backend /app/.venv/bin/python -m app.exportdb --out /data/biblioteca.json
	docker cp alucard-backend-1:/data/biblioteca.json data/biblioteca.json

catalog: ## Genera el catálogo interno clasificado (data/catalogo.json)
	docker compose exec -T backend /app/.venv/bin/python -m app.catalog --out /data/catalogo.json
	docker cp alucard-backend-1:/data/catalogo.json data/catalogo.json

versiones: ## Auditoría de versiones local (uv local, desde backend/)
	cd backend && uv run python -m app.versiones --out ../data/version_audit.json

versiones-oficial: ## 1:1 con BD oficial {title_id: "x.y.z"} en data/oficial.json
	cd backend && uv run python -m app.versiones --oficiales ../data/oficial.json --out ../data/version_audit.json

versiones-resolver: ## Resuelve todos los títulos a title-id Nintendo (red)
	cd backend && uv run python -m app.versiones --resolver 5374 --out ../data/version_audit.json

versiones-daemon: ## Daemon blindado (docker) de auditoría Nintendo
	docker compose restart backend-versiones

versiones-status: ## Estado del daemon Nintendo
	docker compose logs --tail 8 backend-versiones

