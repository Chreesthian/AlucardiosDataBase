# AGENTS.md

Instructions for AI coding agents (Claude Code, GitHub Copilot, Cursor, and
similar) working in this repository.

## Repository Identity

AlucardiosDataBase is a self-hosted web application that turns a MEGA Switch
library dump into a browsable catalog enriched with IGDB metadata. It is
backend-first (FastAPI + SQLAlchemy + SQLite) with an Astro SSR frontend and a
Docker Compose deployment of supervised workers.

## Layout

- `backend/app`: Python application package.
  - `parser.py`, `ingest.py`, `library.py`, `catalog.py`: dump and catalog.
  - `igdb.py`, `enrich.py`: IGDB connector and enrichment pipeline.
  - `sync.py`: incremental synchronization.
  - `versiones.py`: Nintendo title-id audit.
  - `indexar_descargas.py`, `megacmd.py`: MEGA download index.
  - `routers/`: FastAPI routes.
  - `tests/`: pytest suite.
- `frontend/src`: Astro pages, components, styles.
- `frontend/public`: static assets and PWA files.
- `docker-compose.yaml`: API, frontend, and workers.
- `e2e/`: Playwright audit against a live deployment.

## Golden Rules

- Never print, log, or commit secrets (`.env`, IGDB credentials, MEGA
  sessions). Prefer reading from environment variables.
- Never commit generated artifacts: `data/*` (SQLite, JSON exports), MEGA
  dumps, `node_modules/`, `.venv/`, `dist/`.
- Preserve the existing architecture: do not add ad-hoc processes that
  duplicate `app.sync`, `app.enrich`, or `app.versiones` daemons. Extend the
  supervised workers instead.
- Keep the incremental sync destructive guard: a dump with zero files must
  never wipe the catalog unless `--allow-vacio` is passed explicitly.
- Write atomic JSON (see `backend/app/safefs.py`) for exported artifacts.
- Use the shared SQLite engine (`build_engine` in `backend/app/db.py`) with
  WAL and busy timeout; do not create raw engines.
- Keep frontend and backend source in sync with their lockfiles
  (`uv.lock`, `pnpm-lock.yaml`).

## Running the Project

### Backend tests

```bash
cd backend
uv sync
uv run pytest
```

### Frontend build

```bash
cd frontend
pnpm install
pnpm build
```

### Full stack

```bash
docker compose up -d --build
docker compose ps
```

### End-to-end audit (requires the stack running)

```bash
cd e2e
pnpm install
pnpm exec playwright install chromium
pnpm test
```

## Conventions

- Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`).
- Human communication in issues and pull requests is in English.
- Generated diagnostics belong under `scripts/` or `data/` (never committed).
- When touching IGDB queries, verify field expansions against the live API
  before assuming a nested field exists (some fields, for example community
  time-to-beat data, are not exposed by the public API).
