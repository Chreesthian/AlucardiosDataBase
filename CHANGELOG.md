# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Weekly credential rotation support (different account, same library):**
  `scripts/lib/mega_session.sh` loads `MEGA_EMAIL`/`MEGA_PASSWORD` (env, repo
  `.env`, or `~/.config/alucard/mega.env` written by `make credenciales`) and
  re-logs in by itself when the active MEGAcmd session belongs to a previous
  account (`mega-logout --keep-session` → `mega-login`; if the login fails it
  restores the previous session and exits rc=4 instead of leaving the host
  without MEGAcmd). `scripts/refrescar_volcado.py` aborts without writing when
  the candidate dump loses a sector that currently carries files
  (`--permitir-sectores-perdidos` overrides), and `GET /api/sync/status` +
  `/novedades` expose the stable `dump_fuente` (the share) next to the rotating
  account, so a rotation that does not reach the library fails loudly and never
  empties the catalog.
- **Share rotation remap in `app.sync`:** when the weekly share is renamed (for
  example `INSHARE owner:BCKP1` → `INSHARE other:BCKP2`) with equivalent content,
  the incremental sync detects it, rewrites the stored `nodes.path` prefix and
  resets the cached download links to `pendiente` instead of deleting and
  re-adding ~31k nodes: `node_id`s, titles and IGDB enrichment survive and
  "Novedades" only records the files that are really new.
- "Novedades" section (backend + frontend): `novedades` table, populated by the
  incremental sync with the games added and the titles that received new update
  or DLC files (`juego_nuevo` / `update_nuevo` / `dlc_nuevo` / `contenido_nuevo`).
  New endpoints `GET /api/novedades` (with `tipo` filter and summary counters) and
  the SSR page `/novedades`, linked from the top navigation.
- **Dump refresh automation (root cause of the silent update lag):**
  `scripts/autovolcado.sh` (+ `make volcado-auto`, `make volcado-cron`,
  `make volcado-cron-off`, `make volcado-estado`) regenerates the canonical dump
  from the host MEGAcmd session and asks the API for the incremental scan, so
  the catalog and "Novedades" stop depending on someone remembering `make
  volcado`. It fails loudly: rc=4 without a MEGA session, rc=5 when the refresh
  fails, rc=6 when the API scan fails, with the reason in `data/volcado.log`,
  `data/volcado_estado.json` and on stderr (cron mail).
- **Staleness guard for the sync watcher:** `app.sync --watch` checks how old the
  dump is on every cycle (`--max-edad`, default `ALUCARD_SYNC_MAX_EDAD_HORAS=26`,
  `--seguir-si-obsoleto` to only warn) and exits with rc=3 instead of repeating
  "no changes" forever, so a stalled pipeline is visible in `docker compose ps`.
  Info logs are now configured in the daemon, and every pass prints the dump date
  and age.
- `GET /api/sync/status` reports `dump_generated_at`, `dump_age_hours`,
  `dump_max_edad_horas` and `dump_obsoleto`; the `/novedades` page shows a
  warning banner (and the dump date) when the source is stale, so the list is
  never silently incomplete.
- `python -m app.novedades` (+ `make novedades`): lists the events, exports
  `data/novedades.json` and rebuilds a past period from two dumps
  (`--desde/--hasta`), so the section can be seeded with earlier weeks.
- `scripts/refrescar_volcado.py` (+ `make volcado`): regenerates the canonical
  MEGA dump from a live MEGAcmd session (Cloud Drive, Inbox, Rubbish Bin and
  in-shares), keeps the existing sector labels so `app.sync` stays incremental,
  prints the diff before writing and writes in place (same inode) so the Docker
  bind-mount picks the new dump up without restarting the containers.
- Project governance and community files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, AGENTS).
- Bilingual documentation (English and Spanish).
- MIT license.
- Issue and pull request templates.
- Continuous integration workflows (tests, build, dependency and security scans).

### Fixed

- **Update lag root cause:** nothing regenerated `mega_cuenta_contenido_MEGAcmd.txt`,
  so `backend-sync` kept hashing an unchanged file and logged "volcado sin
  cambios" (invisible: the daemon had no logging configured) while the database,
  the catalog and "Novedades" stayed frozen for days. The refresh is now
  automated on the host and its failure is loud (see `scripts/autovolcado.sh`).
- Second destructive guard in `app.sync`: a dump that keeps less than
  `ALUCARD_SYNC_MIN_FRACCION` (default 0.5) of the current files aborts with a
  clear `RuntimeError`/HTTP 400 instead of deleting half of the library, which is
  what a half-written in-place refresh would look like.
- End-to-end audit: the expected dump totals now live in `e2e/tests/helpers.ts`
  (`VOLCADO`), instead of being repeated as literals across the API/UI specs, so
  refreshing the canonical dump only requires updating one place.
- Incremental sync now refreshes the snapshot header (`generated_at`, `account`,
  `tool`) from the current dump, so the API no longer reports the ingestion date
  of the very first dump after a refresh.
- Backend export: the per-version file traversal is rebuilt over the snapshot's
  `parent_id → nodes` map, so `app.sync --export` no longer aborts with a
  `RecursionError` on titles that have version folders (every real library).
- `POST /api/sync/dump`: the dump path is persisted as text instead of a `Path`
  (SQLite cannot bind that type), which made every call return HTTP 500.

## [0.1.0] - 2026-07-09

### Added

- Backend (FastAPI / SQLAlchemy / SQLite) with parser and ingestion of MEGAcmd dumps.
- Internal catalog (bucket, title and version roles) and JSON exports with atomic writes.
- IGDB enrichment (match and extended game detail) with refresh mode.
- Incremental synchronization (watch mode, empty-dump guard) preserving enrichment.
- Nintendo version audit daemon (title-id resolution).
- MEGA download indexer with resumable cache.
- Frontend (Astro SSR, Tailwind) with cover grid, search, filters and game detail page.
- Progressive Web App (manifest and service worker).
- Docker Compose deployment with supervised workers.
- End-to-end Playwright audit suite.
