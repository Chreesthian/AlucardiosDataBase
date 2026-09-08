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
| `PUBLIC_BACKEND_HOST` / `..._PORT`   | Backend URL baked into the web build      |
| `BACKEND_PORT` / `FRONTEND_PORT`     | Published host ports (Compose)            |

## Operations

The `Makefile` provides the main workflows: `make enrich`, `make sync`,
`make export`, `make catalog`, `make versiones`, `make versiones-daemon`,
`make test`, `make lint` and `make e2e`.

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

