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
  - `plataformas.py`: the OFFICIAL platform of every bucket (dump code → IGDB
    `/v4/platforms`), resolved at runtime for both collections. The dump code
    stays in `titles.letter` (content identity in MEGA); the published name is
    `plataforma`. Never store it in the DB or invent a name for a code that is
    not mapped (`conocido=False`).
  - `ingest.py` also defines the **collection** semantics (`switch` | `retro`).
  - `igdb.py`, `enrich.py`: IGDB connector and enrichment pipeline
    (`--coleccion retro` cleans ROM dump names before matching; the supervised
    worker `backend-retro-enrich` enriches the retro DB). The enrichment also
    materializes IGDB's canonical identity per title (`titles.igdb_name`,
    `igdb_name_norm`, `igdb_year`); the real ROM/folder name stays in
    `titles.name`, and `app.enrich --campos` refreshes those columns from the
    stored sheets without calling IGDB.
  - `sync.py`: incremental synchronization (`--coleccion` for the retro DB).
  - `novedades.py`: new-games/new-content events (sección "Novedades").
  - `versiones.py`: Nintendo title-id audit.
  - `indexar_descargas.py`, `megacmd.py`: MEGA download index.
  - `routers/`: FastAPI routes (`retro.py` serves the separate ROMs catalog).
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
- Keep the freshness guard loud: if the canonical dump is older than
  `ALUCARD_SYNC_MAX_EDAD_HORAS`, `app.sync --watch` must exit with rc=3 (Docker
  restarts it and `docker compose ps` shows the failure). Never silence it to
  make logs prettier: the dump refresh is automated by
  `scripts/autovolcado.sh` (`make volcado-cron`) and a stale dump means the
  database, the catalog and "Novedades" are frozen.
- The canonical dump is generated on the host (MEGAcmd session in `~/.megaCmd`)
  by `scripts/refrescar_volcado.py`; containers cannot regenerate it, so do not
  try to run MEGAcmd inside a worker image.
- MEGA credentials rotate weekly (different accounts, same in-share). Never
  hardcode an account: the pipeline identity is the share label
  (`INSHARE <owner>:<folder>`), credentials come from `scripts/lib/mega_session.sh`
  (`make credenciales`), and a rotation that reaches less data must abort loudly
  (`refrescar_volcado.py` sector guard) instead of emptying the catalog.
- The rotation failover is guided by the LIBRARY, never by the login: an account
  can log in and still mount another share. Keep `verificar_rotacion.elegir_del_pool`
  as the only path that rotates accounts in the pre-flight, keep restoring the
  preferred credential and returning rc=8 when no pool account sees the library
  (never a silent success), and never let a pool password reach a report, a log or
  the API.
- The catalog indexes **only the library** (the in-share sectors,
  `parser.es_biblioteca`). The dump also carries the personal cloud of the account
  that produced it (`CLOUD_DRIVE`, `INBOX`, `RUBBISH_BIN`) and that cloud changes
  with the weekly rotation, so it must never be ingested or turned into
  "Novedades": report it (`stats["ignorados_fuera_biblioteca"]`, `nube_propia` in
  `GET /api/sync/cuentas`) instead of indexing it.
- The retro ROMs collection is a **separate catalog**: another in-share
  (`INSHARE …:ORTIK 90`), another account of the pool, its own dump
  (`data/mega_retro_contenido_MEGAcmd.txt`) and its own database
  (`data/retro.db`). Never ingest it into `alucard.db`, never serve it from the
  `/api/*` Switch endpoints, and never let `/retro` share state with `/`. Keep
  `app.ingest`/`app.sync` parametrised by `--coleccion` (`role_of` and
  `_rol_hijo` must stay in sync), and keep `scripts/volcado_retro.sh` restoring
  the preferred credential on exit: the host has ONE MEGAcmd session and the
  Switch pipeline is the priority. Its IGDB enrichment is its own supervised
  worker too (`backend-retro-enrich` → `app.enrich --db /data/retro.db
  --coleccion retro`): never point it at `alucard.db`, and keep the shared
  `/api/retro/*` endpoints reading `app.state.engine_retro`.
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
