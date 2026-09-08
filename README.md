# AlucardiosDataBase

WebApp que representa **en tiempo real** el contenido de una cuenta MEGA como una
biblioteca de juegos navegable (grid de carátulas, búsqueda, detalle de
títulos/versiones/archivos), con un frontend cuya experiencia replica la de
[`proyecto-heredado`](../proyecto-heredado) (el clon local de
[Scrob](https://github.com/ellite/scrob)) y un backend moderno.

Pila:

| Capa    | Stack                                                        | Gestor |
| ------- | ------------------------------------------------------------ | ------ |
| Backend | Python · FastAPI · SQLAlchemy 2 · SQLite (→Postgres)         | `uv`   |
| Sincr.  | MEGAcmd (`mega-ls -R -l`) · volcados `.txt` · eventos (SSE)  | —      |
| Front   | Astro (SSR, `@astrojs/node`) · Tailwind v4 · TypeScript      | `pnpm` |
| Metad.  | IGDB (credenciales de `un-conector-anterior/.env`) — fase M6 | —      |

Puertos por convención (igual que scrob): **frontend 7330 · backend 7331**.

## Estado

Fase 0 (cimientos) — ver `docs/PLAN.md`.

## Inicio rápido

```bash
# 1) Backend (crea .venv e instala)
cd backend
uv sync
cp .env.example .env            # ajustar rutas/credenciales si hace falta

# 2) Ingesta del volcado MEGA en SQLite
uv run python -m app.ingest --dump ../mega_cuenta_contenido_MEGAcmd.txt

# 3) Arrancar API
uv run uvicorn app.main:app --port 7331 --reload
# docs en http://localhost:7331/docs

# 4) Frontend
cd ../frontend
pnpm install
pnpm dev                        # http://localhost:7330
```

Tests del backend: `uv run pytest` dentro de `backend/`.

## Despliegue con Docker (producción)

Dos imágenes multi-stage y sin-root: `alucard/backend` (Python/uv/FastAPI) y
`alucard/frontend` (Node/Astro SSR). El stack compone, ingiere el volcado en el
primer arranque (idempotente) y persiste la BD en un volumen.

```bash
cp .env.example .env        # puertos/credenciales (opcional)
make build                  # o: docker compose build
make up                     # o: docker compose up -d --build

# web  → http://localhost:7330
# api  → http://localhost:7331/api/health   (docs: /docs)
```

- El volcado canónico se monta en solo lectura desde
  `./mega_cuenta_contenido_MEGAcmd.txt` → `/dump/…` del contenedor backend.
- La BD SQLite vive en el volumen `alucard-data` (`/data/alucard.db`);
  el backend ingiere **solo si está vacía** (`--if-empty`).
- Credenciales IGDB (opcionales): `backend/.env` (creado con
  `scripts/bootstrap_env.py`) o variables `ALUCARD_IGDB_*` en `.env` raíz.
- Carátulas y **ficha IGDB completa** (sinopsis, storyline, ratings, PEGI,
  plataformas/géneros/modos, desarrollador/editor, capturas, vídeos, webs y
  similares): tras desplegar, ejecuta `make enrich` para resolver/actualizar;
  progreso en `/api/enrich/status` (`fichas_completas`, `covers`, `pendientes`).
- Base local profesional: SQLite (snapshots, nodos, títulos + ficha IGDB en
  `igdb_json` versionada) y exportación a JSON estructurado con
  `make export` → `data/biblioteca.json`.
- **Actualización incremental** (`make sync`): escanea el volcado y aplica solo
  las diferencias (añadidos/borrados/cambios) **sin reconstruir** la BD ni
  perder el enriquecimiento IGDB de lo que persiste. Registro de cada escaneo
  en `/api/sync/status` (`ultimo_escaneo`). Programación típica (crontab):
  `*/30 * * * * cd /ruta/AlucardiosDataBase && make sync >> /tmp/alucard-sync.log 2>&1`
- **Catálogo interno clasificado** (`make catalog` → `data/catalogo.json`):
  indexa y clasifica TODO el árbol MEGA (sectores, 27 carpetas de letra con sus
  juegos/archivos/bytes, versiones Base/Actualización/DLC y familias de formato
  RAR/NSP/NSZ…). API: `GET /api/catalog` y
  `GET /api/catalog/folder?path=<path>` para inspeccionar cualquier carpeta.
- Comandos: `make logs`, `make ps`, `make down`, `make restart`.
- Si 7330/7331 están ocupados en el host (p. ej. por otro scrob), cambia
  `FRONTEND_PORT`/`BACKEND_PORT` en `.env` y reconstruye el frontend.
- API hacia el frontend: URL horneada en el build (`PUBLIC_BACKEND_HOST`).

## Estructura

```
backend/   API + parser del volcado + ingesta + sync MEGAcmd (uv)
frontend/  WebApp Astro (pnpm), misma arquitectura de proyecto-heredado
docs/      PLAN.md (hoja de ruta) y documentación de arquitectura
data/      BD SQLite de runtime (gitignored)
mega_cuenta_contenido_MEGAcmd.txt   volcado semilla (fuente primaria)
```

## Notas de seguridad

- El `.env` (con credenciales MEGA/IGDB si se usan) está en `.gitignore`.
- Las credenciales IGDB se leen del proyecto `un-conector-anterior/.env`
  mediante `scripts/bootstrap_env.py` (solo copia las claves `IGDB_*`/`USER_AGENT`).
