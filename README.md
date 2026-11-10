<p align="center">
  <img src="frontend/public/brand/emblem.svg" width="88" height="88" alt="Alucardio emblem">
</p>

# AlucardiosDataBase

**Your MEGA game library, finally looking like a collection.**

AlucardiosDataBase is a self-hosted catalog for a Nintendo Switch library stored
in MEGA. It reads a MEGAcmd dump, enriches titles with IGDB metadata and serves a
fast, editorial web interface for browsing, searching and inspecting the games
you already own.

It is **not a game launcher, a ROM repository or a download service**. It does
not include or distribute game files, and there is no public demo: the app is
designed to serve a private library you control.

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](backend/pyproject.toml)
[![React](https://img.shields.io/badge/React-19-61dafb)](frontend/package.json)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ed)](docker-compose.yaml)

## What it does

- **Browse a real collection.** Use a typographic list or a 2:3 cover grid with
  search, letter filters, ordering and pagination.
- **Open complete game pages.** IGDB covers, synopsis, genres, platforms,
  release data, screenshots and external links, together with the files and
  versions found in your MEGA tree.
- **Keep a separate retro shelf.** Arcade, console and microcomputer ROMs have
  their own catalog and database.
- **See what is new.** “Novedades” highlights games and update/DLC content that
  arrived in the latest dump.
- **Use it anywhere.** Responsive SSR UI, installable as a PWA, with light and
  dark themes and keyboard-visible focus.
- **Stay self-hosted.** Your library, your MEGA account and your machine.

## Run with Docker

Requirements: Docker with Docker Compose, a MEGA account containing your
library, and MEGAcmd on the host to produce the dump. IGDB/Twitch credentials
are optional but recommended for covers and metadata.

```bash
git clone https://github.com/Chreesthian/AlucardiosDataBase.git
cd AlucardiosDataBase
cp .env.example .env
# Optional: set IGDB credentials in .env or backend/.env
docker compose up -d --build
```

Open **http://localhost:7330**. The API and interactive docs run at
`http://localhost:7331` and `http://localhost:7331/docs`.

The stack expects the canonical dump at
`./mega_cuenta_contenido_MEGAcmd.txt` (mounted read-only). The container does not
run MEGAcmd: generate or refresh the dump from the host with your own MEGAcmd
session.

## Library updates

The backend watches the mounted dump and applies changes incrementally. To
refresh the catalog, replace that file with a new dump produced on the host. On
a desktop host with MEGAcmd, the `/actualizar` page can guide the credential
check and the dump refresh; MEGAcmd is never executed inside the container.

MEGA passwords remain on the host, outside the repository and outside the
database. The application never ships them in an image, an API response or a
log.

## Scope and privacy

- The repository contains application code and configuration only.
- The MEGA dump, SQLite database, covers and generated exports are local files.
- `.env`, databases, dumps, logs and local reference material are ignored by Git.
- No game files or third-party binaries are distributed here.

## License

[MIT](LICENSE). The project does not grant any rights over the games, covers or
other third-party content in your library.
