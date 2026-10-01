# AlucardiosDataBase

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](/backend/pyproject.toml)
[![CI](https://img.shields.io/badge/CI-github%20actions-2088ff)](.github/workflows/ci.yml)

Self-hosted game catalog web application for a MEGA-hosted library. The
backend parses a MEGAcmd dump, stores the tree in SQLite, enriches every title
with full IGDB metadata and serves a modern Astro SSR frontend styled after the
Alucardio brand, installable as a PWA.

**Read this in [Español](README.es-ES.md).**

## Features

- **Live catalog from MEGA.** Ingests a `mega-ls -R -l` dump into SQLite with
  idempotent snapshots; the database is never rebuilt from scratch.
- **Incremental sync.** A watcher (`backend-sync`) computes diffs between the
  dump and the database, applying additions/removals without losing the IGDB
  enrichment of unchanged titles. An empty-dump guard prevents accidental
  wipes.
- **IGDB enrichment.** Cover art, full-resolution hero artwork, summary and
  storyline, platforms, genres, game modes, release dates, age ratings,
  languages, developers/publishers, external links, screenshots and videos.
- **Nintendo version audit.** A supervised daemon (`backend-versiones`)
  resolves title-ids and compares local game versions against Nintendo's
  published metadata.
- **Download indexer.** Resolves each version node to its MEGA link with a
  resumable cache (`mega-export`).
- **Internal catalog.** Classifies the whole tree: sectors, per-letter
  folders, format families (RAR/NSP/NSZ...) and Base/Update/DLC roles.
- **Separate retro catalog.** A second MEGA in-share with ROMs (arcade, consoles,
  microcomputers) is indexed into its **own database** and served at `/retro` with
  its own API, so it never mixes with the Switch library.
- **Frontend.** SSR cover grid with search, letter chips, ordering and
  pagination; a rich game detail page; offline-ready PWA.
- **Operational.** Docker Compose stack with supervised workers, atomic JSON
  exports and structured endpoints for the web.

## Architecture

```text
MEGA library ──mega-ls dump──> backend ingestion ──> SQLite (WAL)
                                                         │
        IGDB metadata <── enrich workers ──> catalog & export JSON
                                                         │
                                           FastAPI (REST/SSE) <── Astro SSR + PWA
```

The backend exposes a REST API and structured JSON exports
(`data/biblioteca.json`, `data/catalogo.json`); the frontend consumes the API
only. Every service runs as a non-root container with `restart: unless-stopped`.

## Repository layout

```text
backend/    FastAPI + dump parser, ingestion, sync, enrichment, daemons (uv)
frontend/   Astro SSR + Tailwind v4 + TypeScript + PWA (pnpm)
e2e/        Playwright audit suite (API and UI)
scripts/    Development helpers and diagnostics
docs/       Roadmap (PLAN.md) and research notes
.github/    Issue/PR templates, CI, Dependabot, CodeQL
data/       Runtime database and exports (git-ignored)
```

## Getting started

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22 and
[pnpm](https://pnpm.io/).

```bash
# 1) Backend
cd backend
uv sync
cp .env.example .env      # adjust paths/credentials if needed

# 2) Generate a dump from your own MEGA account and ingest it
#    (MEGAcmd: mega-ls -R -l > mega_cuenta_contenido_MEGAcmd.txt)
uv run python -m app.ingest --dump ../mega_cuenta_contenido_MEGAcmd.txt

# 3) API
uv run uvicorn app.main:app --port 7331 --reload
# interactive docs: http://localhost:7331/docs

# 4) Frontend
cd ../frontend
pnpm install
pnpm dev                 # http://localhost:7330
```

Run the backend tests with `cd backend && uv run pytest`.

## Run with Docker (production)

```bash
cp .env.example .env     # optional: ports/credentials
make up                  # or: docker compose up -d --build
```

| Service             | Purpose                                          | Port  |
| ------------------- | ------------------------------------------------ | ----- |
| `backend`           | FastAPI REST API + JSON exports (docs at `/docs`) | 7331  |
| `frontend`          | Astro SSR web app + PWA                          | 7330  |
| `backend-enrich`    | IGDB enrichment worker                           | —     |
| `backend-sync`      | Incremental dump watcher (adds/removes by diff)  | —     |
| `backend-versiones` | Nintendo version audit daemon                    | —     |

The canonical dump is mounted read-only into the backend container and
ingested on first boot only when the database is empty. SQLite data lives in
the `alucard-data` volume. Useful commands: `make logs`, `make ps`, `make
down`, `make restart`.

### Keeping the library up to date (dump refresh + `backend-sync`)

`backend-sync` can only *apply* diffs: the canonical dump is generated from a
live MEGAcmd session on the host (`scripts/refrescar_volcado.py`), so nothing
inside the containers can regenerate it. That refresh is automated on the host:

```bash
make volcado-auto      # refresh the dump now and apply the incremental scan
make volcado-cron      # install the cron entry (every 6 h, idempotent)
make volcado-estado    # last run + log tail + cron entry
make volcado-cron-off  # remove the cron entry
```

The pipeline is deliberately **fail fast and loud**: `scripts/autovolcado.sh`
exits non-zero when there is no MEGA session or when the refresh/scan fails
(cron then mails the reason and everything is logged to `data/volcado.log`), and
`backend-sync` exits with code 3 when the dump is older than
`ALUCARD_SYNC_MAX_EDAD_HORAS` (26 h) instead of repeating "no changes" forever.
`GET /api/sync/status` exposes `dump_obsoleto`/`dump_age_hours` and the
`/novedades` page renders a warning banner, so a frozen catalog is visible
instead of silent.

### Weekly credential rotation (different account, same library)

The MEGA credentials rotate weekly (different accounts that mount the **same
in-share**). The pipeline is anchored to the share, not to the account:

```bash
make credenciales     # stores this week's MEGA_EMAIL/MEGA_PASSWORD (chmod 600)
# → ~/.config/alucard/mega.env  (or ALUCARD_MEGA_ENV, or MEGA_EMAIL in the env)
```

- If the active session belongs to another account, `scripts/lib/mega_session.sh`
  logs in again on its own (login first; if it fails it **restores** the previous
  session and exits rc=4, so the host is never left without MEGAcmd).
- Before listing anything, `scripts/verificar_rotacion.py` runs a **pre-flight** in
  seconds (`mega-mount` + a non-recursive `mega-ls`) and checks that the active
  session actually mounts the in-share of the current dump and that its root still
  holds the same buckets. If this week's credentials mount a *different* library
  it aborts with **rc=8** without spending minutes on `mega-ls -R -l` and without
  touching the dump; the verdict is written atomically to
  `data/estado_cuentas.json`. `ALUCARD_PREFLIGHT=0` disables it.
  `GET /api/sync/cuentas` publishes that verdict (verdict, rotating account, age,
  what is missing) and `/novedades` warns when this week's credentials mount a
  *different* library, so a frozen catalog is visible instead of silent. In
  Docker the API reads the report through a read-only bind mount
  (`ALUCARD_ESTADO_CUENTAS_PATH=/estado/estado_cuentas.json`); a missing report is
  reported as `disponible: false` and is *not* treated as a failure.
- **Failover guided by the library (`make rotacion`):** logging into MEGA and
  *seeing* the library are two different things — an account of the pool can log in
  and still mount another share, which is why the pre-flight is what decides. When
  this week's credential passes the pre-flight without seeing the library,
  `autovolcado.sh` tries the pool (`~/.config/alucard/mega_cuentas.txt`,
  `ALUCARD_MEGA_CUENTAS`) account by account with the same pre-flight and leaves the
  session on the first one that *does* see it
  (`verificar_rotacion.py --elegir-cuenta`), so the cron keeps refreshing instead of
  failing every 6 h. If no account of the pool sees it, the preferred credential is
  restored and it aborts with rc=8 exactly as before. `ALUCARD_ROTACION=0` disables
  the failover, `ALUCARD_ROTACION_PERSISTIR=1` also stores the chosen account as the
  preferred credential (chmod 600, outside the repo) and no password ever reaches
  the report, the logs or the API.
- `refrescar_volcado.py` aborts (rc=1, nothing written) if the candidate dump
  loses a sector that currently carries files — credentials that cannot reach the
  library can never empty the catalog. `--permitir-sectores-perdidos` overrides
  it for an intentional change.
- The same candidate is checked for **title coverage** (game folders): a share
  that is re-shared only partially keeps every sector but ships fewer games, and
  applying it would silently delete titles and their IGDB data. If the new dump
  keeps less than `ALUCARD_MIN_TITULOS_FRACCION` (0.9) of the titles in the
  current one, the refresh aborts too; `--permitir-titulos-perdidos` overrides it.
  `app.sync` enforces the same rule (`--min-titulos-fraccion`, blindaje 3) before
  running the diff, and `POST /api/sync/dump` returns 400 for it.
- `app.sync` diffs by path and the sector label comes from the share
  (`INSHARE <owner>:<folder>`), so rotating the account without real changes
  yields 0 additions/removals: no phantom "Novedades" and no IGDB re-enrichment.
  `GET /api/sync/status` reports the stable `dump_fuente` next to the rotating
  `account`, and `/novedades` shows it.
- **Only the library is indexed.** The dump also carries the sectors that belong
  to the *account* that produced it (`CLOUD_DRIVE`, `INBOX`, `RUBBISH_BIN`) and
  that personal cloud changes with the weekly rotation. `app.sync`/`app.ingest`
  keep just the library sectors (`INSHARE …`), so those files never enter the
  catalog, never show up in "Novedades" and never move the published totals;
  every scan reports what was ignored
  (`stats["ignorados_fuera_biblioteca"]`, logged and printed by the CLI), and the
  pre-flight publishes how many entries the current account keeps outside the
  library (`nube_propia` in `GET /api/sync/cuentas`, shown on `/novedades`). A
  database that already had such noise is cleaned up by the next scan.
- **Share renaming (e.g. `BCKP1` → `BCKP2`)**: when a share disappears and a new
  one appears with equivalent content, `app.sync` detects the rotation, remaps the
  stored paths and resets the cached download links (`pendiente`) instead of
  deleting/rebuilding the catalog, so `node_id`s, titles and IGDB survive while
  only the real new files show up in "Novedades". Re-index the links against the
  new share with `./scripts/enlazar_descargas.sh` (host, resumable).

## Retro collection (separate catalog)

The MEGA account pool also carries a **second, unrelated library**: a retro ROM
collection (arcade, consoles, microcomputers) living in **another in-share**,
mounted by another account of the pool. It is served as a **separate section** so
it can never contaminate the Switch catalog:

- **Its own dump, its own database.** `data/mega_retro_contenido_MEGAcmd.txt` is
  indexed into `data/retro.db` (`ALUCARD_RETRO_DUMP_PATH`,
  `ALUCARD_RETRO_DB_PATH`), never into `data/alucard.db`: `/api/meta`,
  `/api/titles` and `/novedades` keep describing only the Switch library.
- **Its own API and page.** `/api/retro/meta|sistemas|titles|titles/{slug}|status`
  plus `/retro` and `/retro/game/{slug}` (reusing `GameCard`).
- **Same IGDB data as the Switch catalog.** ROM names carry dump noise
  (`Tomb Raider (USA).7z`, `(Rev 1)`, `[!]`) that used to sink the matcher, so
  `app.enrich` takes `--coleccion retro` and cleans them
  (`igdb.titulo_para_igdb_rom`) before asking IGDB. The supervised worker
  `backend-retro-enrich` (its own DB, `--coleccion retro`) fills covers, the
  canonical IGDB name and the full sheet, and `/retro/game/{slug}` renders them
  with the **same shared component** as the Switch game page
  (`components/FichaIGDB.astro`). `GET /api/retro/status` publishes the progress
  (`caratulas`, `enriquecidos`, `pendientes_enrich`, `sin_match`). The sweep is
  parallelised (`--concurrencia`, default 4; the connector throttle paces the
  starts to ~3.3 req/s, under IGDB's 4 req/s limit) and every pass logs its real
  pace in titles/min, so a 10k backfill is observable with
  `docker compose logs -f backend-retro-enrich`.
- **A different tree shape.** Level 1 is the SYSTEM (`ARC N-64`, `ARC Mame2003`…)
  and level 2 the games; a game can be a **loose file** (MAME/Atari `.zip`) or a
  folder with its variants (`B-ASE`), and letter folders (`B/`, `#/`) are
  containers, not games. `app.ingest` / `app.sync` implement this through
  `--coleccion retro`.
- **Systems are published by their OFFICIAL name.** That level-1 folder is a
  hand-made dump code and it is the identity of the content in MEGA, so
  `titles.letter` keeps it, but no catalog should show `ARC S3G4-Mega
  Drive-G3N3S1S`: `app.plataformas` (a static catalog built from IGDB's
  `/v4/platforms`) resolves every bucket at runtime to `nombre` / `corto` /
  `igdb_id` / `igdb_slug` / `generacion` / `familia`, and every payload that
  identifies a bucket adds a `plataforma` object next to the untouched `letter`
  (`/api/retro/sistemas`, `/api/retro/titles`, `/api/retro/titles/{slug}`, the
  JSON export and the Switch equivalents). `/retro` chips and badges read *N64*,
  *Mega Drive*, *MAME*… and the `sistema` filter accepts the canonical key
  (`mega-drive`), the official name or the legacy dump code, so old links keep
  working. A code that is not in the catalog is shown as-is with
  `conocido=False` (never invented) and the chip flags it; `Sega NAOMI`,
  `Atomiswave` and `ScummVM` are published with `igdb_id=None` because IGDB does
  not have them as platforms.
- **The catalog is read by the OFFICIAL name.** IGDB's canonical title and
  original release year live in their own columns (`igdb_name`,
  `igdb_name_norm`, `igdb_year`) while the ROM file/folder name stays in `name`
  — it is what identifies the content in MEGA. `/retro` is titled, searched
  (`q=Three Wonders` finds `3wonders.zip`) and **sorted by it by default**
  (`sort=canonico`; `sort=year` sorts by era), showing the ROM file underneath
  the cover (cards, autosuggest, detail header and page `<title>`);
  `GET /api/retro/status` adds `con_nombre_oficial`. Existing databases get the
  columns automatically at startup (`app.db.migrar_esquema`) and
  `make enrich-retro-campos` (or `make enrich-campos` for Switch) backfills them
  from the sheets already stored, **without calling IGDB**.
- **Refresh on the host (cron).** `scripts/volcado_retro.sh` (`make volcado-retro`)
  rotates MEGAcmd to the account that actually *sees* the ROMs in-share
  (`verificar_rotacion.py --volcado … --elegir-cuenta` — library-guided, never
  login-guided), refreshes the dump, **always restores the preferred Switch
  session** on exit (trap) and asks the API to scan its own DB
  (`POST /api/retro/dump`). Install it with `make volcado-retro-cron` (every 6 h,
  offset 30 min from the Switch cron); `make volcado-retro-estado` shows the last
  run and `make retro-status` the freshness endpoint. `backend-retro-sync` is the
  safety-net worker.
- **Isolation by construction.** Every retro endpoint reads
  `app.state.engine_retro`, so a mistake on one collection cannot touch the other.

Rough start-up:

```bash
make retro-credenciales   # store the account that sees the retro in-share (chmod 600, outside the repo)
make volcado-retro        # first dump + scan (bootstraps data/retro.db)
make volcado-retro-cron   # keep it fresh every 6 h
```

`GET /api/retro/status` (`make retro-status`) reports dump freshness, its in-share
`volcado_fuente`, the number of systems/games and an `aviso` to surface in the UI
when the dump is missing or stale.

## Configuration

The backend reads `ALUCARD_*` variables (see `backend/.env.example`); the
frontend build embeds `PUBLIC_BACKEND_HOST`/`PUBLIC_BACKEND_PORT` (see
`frontend/.env.example`).

| Variable                             | Meaning                                   |
| ------------------------------------ | ----------------------------------------- |
| `ALUCARD_DUMP_PATH`                  | Path to the MEGAcmd dump                  |
| `ALUCARD_DATABASE_URL` / `ALUCARD_DB_PATH` | SQLite path or Postgres URL        |
| `ALUCARD_API_PORT`                   | Backend port                              |
| `ALUCARD_CORS_ORIGINS`               | Allowed frontend origins                  |
| `ALUCARD_IGDB_CLIENT_ID` / `..._SECRET` | IGDB credentials (also `IGDB_*`)    |
| `ALUCARD_SYNC_MAX_EDAD_HORAS`        | Max dump age before the sync watcher fails (def. 26) |
| `ALUCARD_SYNC_MIN_FRACCION`          | Min file ratio kept by a dump to be applied (def. 0.5) |
| `ALUCARD_SYNC_MIN_TITULOS_FRACCION`  | Min title (game) ratio kept by a dump to be applied (def. 0.9) |
| `ALUCARD_ESTADO_CUENTAS_PATH`        | Pre-flight report read by `GET /api/sync/cuentas` (def. next to the DB) |
| `ALUCARD_RETRO_DUMP_PATH`            | Retro ROMs dump (def. `data/mega_retro_contenido_MEGAcmd.txt`) |
| `ALUCARD_RETRO_DB_PATH` / `..._DATABASE_URL` | Retro catalog DB (def. `data/retro.db`) |
| `PUBLIC_BACKEND_HOST` / `..._PORT`   | Backend URL baked into the web build      |
| `BACKEND_PORT` / `FRONTEND_PORT`     | Published host ports (Compose)            |

## Operations

The `Makefile` provides the main workflows: `make enrich`, `make enrich-retro`,
`make enrich-campos`, `make enrich-retro-campos`, `make sync`,
`make export`, `make catalog`, `make volcado`, `make volcado-auto`,
`make volcado-cron`, `make sync-status`, `make pre-vuelo`, `make rotacion`,
`make volcado-retro`, `make volcado-retro-cron`, `make volcado-retro-estado`,
`make retro-credenciales`, `make retro-status`, `make retro-sync`,
`make versiones`, `make versiones-daemon`, `make test`, `make lint` and
`make e2e`.

## Documentation

- [README (English)](README.md) / [README (Español)](README.es-ES.md)
- [Roadmap and architecture](docs/PLAN.md)
- [Nintendo version audit research](docs/INVESTIGACION_VERSIONES.md)
- [Contributing](CONTRIBUTING.md) / [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md) / [AI agent instructions](AGENTS.md)
- [Changelog](CHANGELOG.md)

## Legal notice

This repository contains code and configuration only. It distributes no game
files and no copyrighted binaries. The MEGA dump, the SQLite database and the
generated exports are user-local artifacts excluded from version control;
content access is managed entirely by the account owner through MEGAcmd.

