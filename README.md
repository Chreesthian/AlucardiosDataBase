<p align="center">
  <img src="frontend/public/brand/emblem.svg" width="88" height="88" alt="Alucardio emblem">
</p>

# AlucardiosDataBase

**Your MEGA game library, finally looking like a collection.**

AlucardiosDataBase is a self-hosted web catalog for a Nintendo Switch library
stored in MEGA. It reads a MEGAcmd dump, enriches each title with IGDB metadata
and serves a fast, editorial interface for browsing, searching, inspecting and
deciding what to play next.

It is **not a game launcher, a ROM repository or a download service**. It does
not include game files; it organizes a library you already own and control.

[Español](README.es-ES.md) · [Operations guide](docs/OPERATIONS.md) · [Contributing](CONTRIBUTING.md)

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](backend/pyproject.toml)
[![React](https://img.shields.io/badge/React-19-61dafb)](frontend/package.json)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ed)](docker-compose.yaml)
[![CI](https://img.shields.io/badge/CI-github%20actions-2088ff)](.github/workflows/ci.yml)

## What you get

- **A library that looks like a collection.** Browse a typographic list or a
  2:3 cover grid, with search, letter filters, ordering and pagination.
- **Everything about a game in one place.** IGDB covers, synopsis, genres,
  platforms, release information, screenshots and external links; plus the
  real files and versions found in your MEGA tree.
- **A separate retro shelf.** Arcade, console and microcomputer ROMs live in
  their own catalog and their own database, so they never mix with Switch.
- **“Novedades” that means something.** A dedicated view of newly added games
  and newly arrived updates or DLC.
- **Comfortable on any screen.** Responsive SSR web app, installable as a PWA,
  with light and dark ink themes.
- **Keyboard-friendly UI.** Visible focus, an accessible selection ring in the
  grid and a subtle accent bar in the list; reduced motion is respected.
- **Self-hosted by design.** Your library, your MEGA account, your machine.
  No account is created here and no library is uploaded to a third party.

## What it is not

- **Not a source of games.** The repository contains code and configuration
  only. The MEGA dump, database, covers and exports are local artifacts.
- **Not a public streaming or download site.** There is no public demo: the app
  is meant to serve a private library that you control.
- **Not an emulator or launcher.** It opens catalog pages, not games.
- **Not a place for credentials.** Passwords, tokens and MEGA sessions stay on
  the host, outside the repository and outside the database.

## A quick look

| Route | What you will find |
| --- | --- |
| `/` | The Switch library: list or grid, search, filters, ordering and pagination |
| `/game/:slug` | The full game sheet: cover, synopsis, metadata, versions, files and links |
| `/novedades` | New games and new update/DLC content detected in the latest dump |
| `/retro` | The separate retro collection |
| `/actualizar` | The guided MEGA update screen on a host with MEGAcmd and the update agent |

The interface is intentionally closer to an editorial catalog than to a game
console clone. The Alucardio identity, typography, paper grain and ink themes
come first; the small console-inspired selection details are only accents.

## Quick start with Docker

### What you need

- Docker Engine with Docker Compose.
- A MEGA account containing **your own** library.
- [MEGAcmd](https://mega.io/cmd) on the host to produce a dump. The containers
  cannot run MEGAcmd or log in to MEGA for you.
- IGDB/Twitch API credentials if you want covers and enriched metadata.

### Start the stack

```bash
git clone https://github.com/Chreesthian/AlucardiosDataBase.git
cd AlucardiosDataBase
cp .env.example .env
# Optional: add your IGDB credentials to .env or backend/.env
docker compose up -d --build
```

Open **http://localhost:7330**. The API and interactive docs are available at
`http://localhost:7331` and `http://localhost:7331/docs`.

The stack expects a canonical dump at `./mega_cuenta_contenido_MEGAcmd.txt`
(it is mounted read-only). Generate or refresh it from the host with your
MEGAcmd session; the complete flow is in the
[operations guide](docs/OPERATIONS.md).

### First library load

```bash
make credenciales   # store the week's rotating MEGA account outside the repo
make volcado        # refresh the dump and apply the incremental scan
```

Then open the web app. On a desktop host with MEGAcmd, `/actualizar` can guide
you through the same process from the browser. No MEGA password is stored in
SQLite, returned by the API or written to a log.

## Privacy and security

- MEGA credentials are read from private files outside the repository
  (`~/.config/alucard/mega.env`, `chmod 600`).
- The Docker containers receive a dump and the minimum runtime configuration;
  they never receive the MEGA password.
- `.env`, databases, dumps and generated exports are ignored by Git.
- The update agent uses a token-protected Unix socket on the host.
- This repository distributes no game files and no copyrighted binaries.

## Development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+ and
[pnpm](https://pnpm.io/).

```bash
# Backend
cd backend
uv sync
uv run pytest

# Frontend
cd ../frontend
pnpm install
pnpm dev
```

The Playwright audit lives in `e2e/` and expects the stack to be running:

```bash
cd e2e
pnpm install
pnpm exec playwright install chromium
pnpm test
```

## Documentation

- [Operations guide](docs/OPERATIONS.md) — deployment, MEGA rotation, workers,
  IGDB enrichment, retro catalog and Makefile workflows.
- [Guía de operaciones en español](docs/OPERACIONES.md).
- [Roadmap and architecture](docs/PLAN.md).
- [Nintendo version audit research](docs/INVESTIGACION_VERSIONES.md).
- [Contributing](CONTRIBUTING.md) / [Code of Conduct](CODE_OF_CONDUCT.md).
- [Security policy](SECURITY.md) / [AI agent instructions](AGENTS.md).
- [Changelog](CHANGELOG.md).

## License

[MIT](LICENSE). Use it, adapt it and improve it. The project does not grant any
rights over the games, covers or other third-party content in your library.
