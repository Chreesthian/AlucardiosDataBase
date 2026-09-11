# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project governance and community files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, AGENTS).
- Bilingual documentation (English and Spanish).
- MIT license.
- Issue and pull request templates.
- Continuous integration workflows (tests, build, dependency and security scans).

### Fixed

- Backend export: the per-version file traversal is rebuilt over the snapshot's
  `parent_id → nodes` map, so `app.sync --export` no longer aborts with a
  `RecursionError` on titles that have version folders (every real library).

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
