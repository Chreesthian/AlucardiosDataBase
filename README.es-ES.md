# AlucardiosDataBase

[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](/backend/pyproject.toml)
[![CI](https://img.shields.io/badge/CI-github%20actions-2088ff)](.github/workflows/ci.yml)

Aplicación web autohospedada de catálogo de videojuegos para una biblioteca
alojada en MEGA. El backend interpreta un volcado de MEGAcmd, almacena el
árbol en SQLite, enriquece cada título con metadatos completos de IGDB y sirve
un frontend moderno en Astro SSR con la estética de la marca Alucardio,
instalable como PWA.

**Lee esta página en [English](README.md).**

## Características

- **Catálogo en vivo desde MEGA.** Ingiere un volcado `mega-ls -R -l` en SQLite
  con instantáneas idempotentes; la base de datos nunca se reconstruye entera.
- **Sincronización incremental.** Un vigía (`backend-sync`) calcula diferencias
  entre el volcado y la base de datos y aplica altas/bajas sin perder el
  enriquecimiento IGDB de los títulos que permanecen. Un guardia anti-vaciado
  evita borrados accidentales.
- **Enriquecimiento IGDB.** Carátulas, arte principal en alta resolución,
  sinopsis y storyline, plataformas, géneros, modos de juego, fechas de
  lanzamiento, clasificaciones por edad, idiomas, desarrolladora/editora,
  enlaces externos, capturas y vídeos.
- **Auditoría de versiones Nintendo.** Un demonio supervisado
  (`backend-versiones`) resuelve title-ids y compara las versiones locales con
  los metadatos publicados por Nintendo.
- **Indexador de descargas.** Resuelve cada nodo de versión a su enlace MEGA
  con caché reanudable (`mega-export`).
- **Catálogo interno.** Clasifica todo el árbol: sectores, carpetas por letra,
  familias de formato (RAR/NSP/NSZ...) y roles Base/Actualización/DLC.
- **Frontend.** Rejilla SSR con búsqueda, chips por letra, ordenación y
  paginación; página de detalle enriquecida; PWA instalable y offline.
- **Operativa.** Stack Docker Compose con workers supervisados, exportaciones
  JSON atómicas y endpoints estructurados para la web.

## Arquitectura

```text
Biblioteca MEGA ──volcado mega-ls──> ingesta backend ──> SQLite (WAL)
                                                             │
      Metadatos IGDB <── workers de enriquecido ──> catálogo y JSON export
                                                             │
                                               FastAPI (REST/SSE) <── Astro SSR + PWA
```

El backend expone una API REST y exportaciones JSON estructuradas
(`data/biblioteca.json`, `data/catalogo.json`); el frontend solo consume la
API. Todos los servicios corren como contenedores no-root con
`restart: unless-stopped`.

## Estructura del repositorio

```text
backend/    FastAPI + parser del volcado, ingesta, sync, enriquecido, daemons (uv)
frontend/   Astro SSR + Tailwind v4 + TypeScript + PWA (pnpm)
e2e/        Suite de auditoría Playwright (API y UI)
scripts/    Utilidades de desarrollo y diagnóstico
docs/       Hoja de ruta (PLAN.md) y notas de investigación
.github/    Plantillas de issue/PR, CI, Dependabot, CodeQL
data/       Base de datos y exportaciones en tiempo de ejecución (git-ignored)
```

## Primeros pasos

Requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22 y
[pnpm](https://pnpm.io/).

```bash
# 1) Backend
cd backend
uv sync
cp .env.example .env      # ajusta rutas/credenciales si hace falta

# 2) Genera un volcado de tu propia cuenta MEGA e ingiérelo
#    (MEGAcmd: mega-ls -R -l > mega_cuenta_contenido_MEGAcmd.txt)
uv run python -m app.ingest --dump ../mega_cuenta_contenido_MEGAcmd.txt

# 3) API
uv run uvicorn app.main:app --port 7331 --reload
# documentación interactiva: http://localhost:7331/docs

# 4) Frontend
cd ../frontend
pnpm install
pnpm dev                 # http://localhost:7330
```

Tests del backend: `cd backend && uv run pytest`.

## Despliegue con Docker (producción)

```bash
cp .env.example .env     # opcional: puertos/credenciales
make up                  # o: docker compose up -d --build
```

| Servicio             | Propósito                                      | Puerto |
| -------------------- | ---------------------------------------------- | ------ |
| `backend`            | API REST FastAPI + exportaciones JSON (docs en `/docs`) | 7331 |
| `frontend`           | Web Astro SSR + PWA                            | 7330   |
| `backend-enrich`     | Worker de enriquecido IGDB                      | —      |
| `backend-sync`       | Vigía del volcado (altas/bajas por diff)       | —      |
| `backend-versiones`  | Demonio de auditoría de versiones Nintendo     | —      |

El volcado canónico se monta en solo lectura dentro del contenedor del backend
y se ingiere en el primer arranque únicamente si la base de datos está vacía.
Los datos SQLite viven en el volumen `alucard-data`. Comandos útiles:
`make logs`, `make ps`, `make down`, `make restart`.

## Configuración

El backend lee variables `ALUCARD_*` (ver `backend/.env.example`); el build del
frontend hornea `PUBLIC_BACKEND_HOST`/`PUBLIC_BACKEND_PORT` (ver
`frontend/.env.example`).

| Variable                             | Significado                                  |
| ------------------------------------ | ------------------------------------------- |
| `ALUCARD_DUMP_PATH`                  | Ruta al volcado de MEGAcmd                   |
| `ALUCARD_DATABASE_URL` / `ALUCARD_DB_PATH` | Ruta SQLite o URL Postgres            |
| `ALUCARD_API_PORT`                   | Puerto del backend                           |
| `ALUCARD_CORS_ORIGINS`               | Orígenes del frontend permitidos             |
| `ALUCARD_IGDB_CLIENT_ID` / `..._SECRET` | Credenciales IGDB (también `IGDB_*`)    |
| `PUBLIC_BACKEND_HOST` / `..._PORT`   | URL del backend horneada en el build web     |
| `BACKEND_PORT` / `FRONTEND_PORT`     | Puertos publicados en el host (Compose)      |

## Operaciones

El `Makefile` agrupa los flujos principales: `make enrich`, `make sync`,
`make export`, `make catalog`, `make versiones`, `make versiones-daemon`,
`make test`, `make lint` y `make e2e`.

## Documentación

- [README (Español)](README.es-ES.md) / [README (English)](README.md)
- [Hoja de ruta y arquitectura](docs/PLAN.md)
- [Investigación de auditoría de versiones](docs/INVESTIGACION_VERSIONES.md)
- [Guía de contribución](CONTRIBUTING.md) / [Código de conducta](CODE_OF_CONDUCT.md)
- [Política de seguridad](SECURITY.md) / [Instrucciones para agentes de IA](AGENTS.md)
- [Registro de cambios](CHANGELOG.md)

## Aviso legal

Este repositorio contiene únicamente código y configuración. No distribuye
ficheros de juegos ni binarios con derechos de autor. El volcado de MEGA, la
base de datos SQLite y las exportaciones generadas son artefactos locales del
usuario excluidos del control de versiones; el acceso al contenido lo gestiona
por completo el propietario de la cuenta a través de MEGAcmd.

