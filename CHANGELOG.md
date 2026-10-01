# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Separate retro collection (ROMs) with its own database, API and page:** the
  account pool also carries a second, unrelated library — a retro ROM collection
  (arcade, consoles, microcomputers) living in **another in-share** — so it is
  indexed in `data/retro.db` (`ALUCARD_RETRO_DB_PATH`,
  `ALUCARD_RETRO_DUMP_PATH`) and served at `/retro` (`/api/retro/meta|sistemas|
  titles|titles/{slug}|status|dump`), **never** mixed with the Switch catalog
  (`/api/meta`, `/api/titles`, `/novedades` stay untouched; the app holds a second
  engine and `tests/test_retro.py` asserts the isolation). Its tree is different
  and `app.ingest`/`app.sync` now take `--coleccion retro`: level 1 is the system
  (`ARC N-64`, `ARC Mame2003`…), a game may be a **loose file** (MAME/Atari) or a
  folder with its variants (`B-ASE`), and letter folders (`B/`, `#/`) are
  containers (`role=group`) whose children are promoted instead of showing up as
  fake games. `Title.letter` holds the system in this collection (SQLite needs no
  migration to widen it from 2 to 64 chars).
- **IGDB enrichment for the retro collection (`backend-retro-enrich`):** the ROMs
  DB (`data/retro.db`) now gets the same covers, canonical name and full sheet as
  the Switch catalog. `app.enrich` takes `--coleccion` and, for `retro`, cleans
  the dump noise off the ROM names **before** matching
  (`igdb.titulo_para_igdb_rom`: extension, `(USA)`/`(Europe)`, `(Rev 1)`,
  `(En,Fr,De,Es,It)`, `[!]`…), which used to push the shared-token ratio below the
  0.5 confidence gate and leave most of the collection without a sheet; MAME short
  ROM names (`aof.zip`) stay as-is and are reported as `miss`. The worker mirrors
  `backend-enrich` against its own DB (`--db /data/retro.db --coleccion retro
  --daemon`), so titles added by `backend-retro-sync` are enriched on the next
  pass and `app.sync` keeps preserving `igdb_*` on re-scans. `GET
  /api/retro/status` now publishes the progress (`caratulas`, `enriquecidos`,
  `pendientes_enrich`, `sin_match`) and `make enrich-retro` runs a pass by hand.
- **Shared IGDB sheet component (`components/FichaIGDB.astro`):** the whole IGDB
  sheet (hero artwork, cover, ratings, PEGI/ESRB, synopsis, storyline, releases,
  supported languages, links + the IGDB entry, tech data, videos, screenshots and
  similar games) was extracted from `game/[slug].astro` so `/retro/game/{slug}`
  renders **exactly the same** markup (its own system chip and content list enter
  through the `badge`/`contenido` slots). The canonical IGDB name
  (`nombre_oficial`) is shown as a subtitle only when it differs from the raw
  name (`Tomb Raider (USA).7z` → *Tomb Raider*), so the thousands of already
  correct titles stay unchanged.
- **Retro refresh pipeline (`scripts/volcado_retro.sh`):** picks the account that
  actually *sees* the ROMs in-share with the same library-guided failover as the
  Switch pre-flight (`verificar_rotacion.py --volcado … --elegir-cuenta`), so the
  ROMs account can never be used for the Switch dump and an already-valid session
  is never rotated; refreshes its own dump
  (`data/mega_retro_contenido_MEGAcmd.txt`) and asks the API to scan its own DB
  (`POST /api/retro/dump`). On exit it puts the host **back on a Switch session**
  in three steps (preferred credential → pool failover guided by the canonical
  dump → resume the exact session that existed before, whose key was captured up
  front) and, if it cannot, it fails loud with rc=9 instead of pretending. The
  restore helpers are invoked with the **Switch** credentials file explicitly,
  because the script exports `ALUCARD_MEGA_ENV=$RETRO_ENV` for its own pre-flight
  and the helpers were reading the retro file (often absent): step 1 never even
  attempted the login and every run escalated to the pool failover.
  `make volcado-retro`, `make volcado-retro-cron` (cron every 6 h, offset 30 min
  from the Switch one), `make volcado-retro-estado`, `make retro-credenciales`,
  `make retro-status` and `make retro-sync`; the `backend-retro-sync` worker keeps
  the freshness guard (rc=3 when its dump goes stale) and the `backend` image also
  mounts the dump read-only.
- **`make retro-sync` / `retro-status` / `sync-status` pointed at the wrong port:** the
  recipes read `$${BACKEND_PORT:-7331}` from the shell, but the Makefile never loads
  `.env` (where `BACKEND_PORT=7441` lives), so the targets hit a port nothing publishes.
  The variable is now resolved from `.env` (same fallback chain as
  `scripts/volcado_retro.sh`) and exported, so the targets work out of the box.
- **`fuente_volcado` accepts share names with spaces:** the extractor used `\S+`
  and silently returned `None` for a real share like `INSHARE …:ORTIK 90`
  (the ROMs in-share). Now `GET /api/sync/status` and `/api/retro/status` publish
  the right stable source for both collections.
- **MEGAcmd answers before the session is actually mounted:** `mega-login` can
  return rc=0 while `mega-whoami` still shows the previous account (~2-7 s in the
  host), and `mega-logout --keep-session` can still be closing when the next login
  arrives (rc=54 "Already logged in"). Reading the account right after the login
  made a **correct** login look failed (the retro run escalated to the pool
  failover with the session already on the right account, and each extra attempt is
  another rotation on a single-session host). Both paths now wait, bounded, for the
  session to settle — `mega_esperar_cuenta` in `scripts/lib/mega_session.sh` and
  `explorar_cuentas_mega._esperar_cuenta` (used by `guardar_sesion`, which also
  retries the rotation once before restoring the previous session). Timeouts are
  env-tunable (`MEGA_ESPERA_LOGIN` 90 s, `MEGA_ESPERA_LOGIN_FALLO` 15 s,
  `MEGA_ESPERA_LOGOUT` 30 s).
- **Rotation failover guided by the library (`--elegir-cuenta`):** logging into MEGA
  and *seeing* the library are two different things — an account of the pool can log
  in and still mount another share — so the pre-flight, not the login, is what
  decides. When this week's credential passes the pre-flight without seeing the
  library, `scripts/autovolcado.sh` tries the pool
  (`~/.config/alucard/mega_cuentas.txt`, `ALUCARD_MEGA_CUENTAS`) account by account
  with `verificar_rotacion.py --elegir-cuenta` and leaves the session on the first
  one that *does* see it (the script no longer depends on who measures: `medir` and
  `informe_de` are now independent of `main`), so the cron keeps refreshing instead
  of sitting on rc=8 every 6 h. If no account of the pool sees it, the preferred
  credential is restored and the pre-flight still fails with rc=8. The report grows
  `modo`, `cuenta_anterior`, `elegida`, `origen`, `candidatas`, `pool`, `inicial` and
  `restaurado` — never a password — and `--guardar-elegida` stores the chosen account
  as the preferred credential (chmod 600, outside the repo). `ALUCARD_ROTACION=0`
  disables the failover and `ALUCARD_ROTACION_PERSISTIR=1` makes the persistence
  opt-in; `make pre-vuelo` and `make rotacion` run both host-side modes.
- **The catalog only indexes the library:** the dump also carries the sectors of
  the ACCOUNT that produced it (`CLOUD_DRIVE`, `INBOX`, `RUBBISH_BIN`) and that
  personal cloud changes with the weekly rotation (real case: one account with an
  empty cloud and another with two personal videos, same in-share). `app.ingest`
  and `app.sync` keep only the library sectors (`parser.es_biblioteca`), so those
  files never enter the catalog, never become "Novedades" and never move the
  published totals (`total_files`/`total_folders` describe the catalog;
  `total_files_volcado`/`total_folders_volcado` the raw dump). Every scan reports
  what was ignored (`ignorados_fuera_biblioteca`, logged and printed by the CLI)
  and the pre-flight exposes how many entries the current account keeps outside
  the library (`nube_propia` in `GET /api/sync/cuentas`, shown on `/novedades`).
  A database that already had that noise is cleaned up by the next scan.
- **Pre-flight for the weekly rotation (`GET /api/sync/cuentas`):**
  `scripts/verificar_rotacion.py` checks in seconds (`mega-mount` + a
  non-recursive `mega-ls`) that the active MEGA session mounts the in-share of the
  canonical dump and that its root still holds the known buckets, and writes the
  verdict atomically to `data/estado_cuentas.json` (rc=4 without session, rc=8 when
  this week's credentials mount another library, both *before* spending minutes on
  `mega-ls -R -l` and without touching the dump). `GET /api/sync/cuentas`
  publishes it (verdict, rotating account, age, missing in-shares/buckets) and
  `/novedades` warns when the credentials of the week do not see the library; a
  missing or unreadable report is `disponible: false` and is *not* a failure, so
  `ALUCARD_PREFLIGHT=0` does not raise a permanent alarm.
- **Per-account diagnosis (`scripts/explorar_cuentas_mega.py`, host):** compares
  the MEGA accounts of the rotation with each other and against the current dump —
  in-shares, quotas, size, titles per letter, exclusive titles and same-title
  complements — and writes `data/reporte_cuentas_mega.{json,md}` with a
  recommendation of which account can run `make volcado-cron` and which one mounts
  a *different* library that must not be mixed in. Passwords are never printed nor
  written to the report.
- **Title coverage guard (partially re-shared library):** a share that is
  re-shared in halves keeps every sector but ships fewer games, and applying it
  would delete titles and their IGDB data in silence. `refrescar_volcado.py`
  aborts (rc=1, nothing written) when the candidate keeps less than
  `ALUCARD_MIN_TITULOS_FRACCION` (0.9) of the titles of the current dump
  (`--permitir-titulos-perdidos` overrides it), `app.sync` enforces the same rule
  before running the diff (`--min-titulos-fraccion`, blindaje 3, default
  `ALUCARD_SYNC_MIN_TITULOS_FRACCION`) and `POST /api/sync/dump` returns 400 for
  it. The canonical count lives in `app.ingest.contar_titulos*`, so the host and
  the database share one definition of "title".
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
- **Official IGDB names as first-class catalog data (`igdb_name`):** the dump name
  used to be the only title, so cards and the browser kept reading
  `After Burner.zip` even with the cover already resolved. Each sheet now
  materializes IGDB's canonical title and original release year in
  `titles.igdb_name` / `igdb_name_norm` / `igdb_year` (`app.enrich`, both
  collections); the real file/folder name stays in `titles.name` as the identity
  of the content in MEGA. `/api/retro/titles` now searches by official name as
  well (`q=Three Wonders` finds `3wonders.zip`), `GET /api/retro/status` publishes
  `con_nombre_oficial` and `/retro` shows the official name with the ROM file
  underneath (cards, autosuggest, detail header and `<title>`; the shared
  `FichaIGDB` inverts its header for retro through `priorizarCanonico`). The JSON
  export carries `nombre_oficial`/`anio`. Deployed databases get the columns with
  an idempotent `ALTER TABLE` at startup (`db.migrar_esquema`, called by
  `create_schema`), and `app.enrich --campos` backfills rows enriched before the
  fields existed **without touching IGDB** (no quota, no re-matching), so the
  thousands of already-resolved titles named themselves instantly.
- New `sort=year` (era) for both catalogs and `sort=canonico` (official IGDB
  name) in `library.list_titles`; retro defaults to the canonical one, so the
  collection reads as a catalog instead of a file list (chips became *Nombre
  oficial / Fichero / Época / Tamaño / Archivos*). The Switch catalog keeps its
  own default (`sort=name`), unchanged.
- **Official platform names for every bucket (`app.plataformas`):** the retro
  collection's level 1 is a hand-made dump CODE (`ARC N-64`, `ARC S3G4-Mega
  Drive-G3N3S1S`, `ARC ScummVM`…), which was being published raw as the system of
  each game — cards, chips, detail badge, JSON export and the `sistema` filter all
  showed that code. A new single source of truth (`app.plataformas`, ~40 systems
  with the data of IGDB's `/v4/platforms`: `nombre`, `corto`, `igdb_id`,
  `igdb_slug`, `generacion`, `familia`) now resolves it **at runtime** (no
  migration, no stale columns) and every payload that identifies a bucket carries
  a `plataforma` object next to the untouched `letter` (the content identity in
  MEGA): `GET /api/retro/sistemas`, `/api/retro/titles`,
  `/api/retro/titles/{slug}` and the Switch equivalents. `letter` still works
  everywhere — the `sistema` filter now also accepts the canonical key
  (`mega-drive`) or the official name (`Sega Mega Drive/Genesis`), so the new UI
  links are readable while old ones keep resolving; a dump code that is not in the
  catalog is published as-is with `conocido=False` (never invented) and the chips
  warn about it. Retro chips/badges now read *N64* / *Mega Drive* instead of
  `ARC N-W!!`, the JSON export carries `plataforma`, and the Switch detail badge
  reads *Nintendo Switch* instead of a bare letter (`Sega NAOMI`, `Atomiswave`
  and `ScummVM` deliberately have `igdb_id=None`: IGDB has no such platforms).

### Changed

- **IGDB sweep throughput (retro backfill):** enriching 10k ROMs used to crawl at
  ~26 titles/min: `mejor_juego_v3` fired up to 7 search calls per title and kept
  them strictly serial, so a title cost 4.6 requests (≈0.3 s throttle + latency
  each = 2.3 s) at ~2 req/s while IGDB allows 4. The matcher now searches the
  **clean term first** and stops as soon as the match is unambiguous
  (`igdb._eleccion_inequivoca`: decorative core or exact identity — criteria that
  provably return what the full matcher would, so match quality is unchanged),
  and `app.enrich` overlaps the requests with a thread pool (`--concurrencia`,
  default 4) paced by the connector throttle (~3.3 req/s, below the 4 req/s
  limit). Only the network is parallel: the SQLAlchemy session is touched
  exclusively from the main thread. Passes now log their real pace
  (`progreso %d/%d … N títulos/min`, `stats["por_min"]`), so a 10k backfill is
  observable instead of opaque.
- **IGDB/HTTP errors no longer become permanent misses:** when *every* search of a
  title failed (429, timeout, network), `mejor_juego_v3` now propagates the error
  so the pass counts it as `error` and retries on a later pass, instead of
  writing `miss` — which `necesita_trabajo` never retries.

### Fixed

- **Phantom "new games" caused by the weekly rotation:** rotating the account
  dragged its personal cloud into the catalog and registered files such as
  `4410_13_SUB.mp4` as `juego_nuevo` in "Novedades" (besides shifting the
  `/api/meta` totals and breaking the end-to-end audit) with zero real changes in
  the library. Only the library sectors are indexed now, previously stored noise is
  removed by the next scan, and `app.novedades.titulo_de` refuses to build an event
  out of a path that is not a bucket inside an in-share, so rebuilding a past
  period (`app.novedades --desde/--hasta`) cannot reintroduce them either.
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
