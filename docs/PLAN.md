# PLAN — AlucardiosDataBase

Objetivo general: un **frontend/backend webapp** que muestra en tiempo real los
juegos alojados en una cuenta MEGA, con una experiencia funcionalmente idéntica
a la de *Scrob* (self-hosted de letterboxd/trakt). Donde Scrob usa TMDB para
películas/series, aquí el catálogo es el árbol MEGA y los metadatos de
carátula/ficha provienen de **IGDB** (credenciales "GamesDb" propias del
despliegue, nunca versionadas).

## Fuente de datos (F0, verificado)

`mega_cuenta_contenido_MEGAcmd.txt` (volcado `mega-ls -R -l`, 46.446 líneas):

| Concepto                    | Valor     |
| --------------------------- | --------- |
| Sectores                    | 4 (Cloud, Inbox, Papelera, **INSHARE BCKP1**) |
| Buckets alfabéticos         | 27 (`-- #`, `-- A` … `-- Z`) |
| Títulos/juegos (FOLDER d2)  | 5.374     |
| Variantes por título (d3)   | 10.205 (`B-ASE`, `U-PD x.y.z`, `D-LC`…) |
| Archivos                    | 30.771 (`.rar`, `.nsp`, `.nsz` → Nintendo Switch) |
| Tamaño total                | 15,97 TiB |

Un *título* es una carpeta de profundidad 2 dentro de un bucket; sus carpetas
hijas son versiones (base/update/dlc); las hojas son los `.partN.rar` o `.nsp`.

## Arquitectura objetivo

```
MEGAcmd (mega-ls -R -l / sync)  ──►  volcado .txt (canon)
        │  sync periódico + SSE          │
        ▼                                ▼
   [backend]  parser ─► Snapshot → Nodos/Títulos (SQL) ─► REST /api ──► [frontend Astro]
                                                              │  carátula IGDB / cover cache
                                                              ▼
                                                    scrob-like UI (grid, buscador, detalle…)
```

Decisiones:
- **Backend**: FastAPI + SQLAlchemy 2 (SQLite WAL por ahora; URL Postgres
  intercambiable por `DATABASE_URL`). Se replica el patrón de scrob
  (`config.py` pydantic-settings, routers, schemas, models).
- **Frontend**: Astro SSR standalone + Tailwind v4 + `src/lib/api.ts`, mismos
  puertos (7330/7331) y misma paleta oscura zinc/azul que scrob.
- **Despliegue**: Docker compose con imágenes multi-stage sin-root
  (`alucard/backend`, `alucard/frontend`), healthchecks, volumen de datos y
  auto-ingesta idempotente en el primer arranque.
- **Tiempo real**: el volcado es el "canon"; un refresco (`mega-ls -R -l`) o
  fichero re-parseado genera un *Snapshot* nuevo e idempotente (el árbol MEGA no
  tiene fechas, así que los snapshots son inmutables y se muestran como tal).
  MEGAcmd real se conecta por MEGAcmd (cuenta ya con sesión en `~/.megaCmd`);
  el módulo `app.megacmd` aísla el binario para poder ejecutarlo en local.
- **Metadatos (IGDB)**: módulo aislado que normaliza `nombre → búsqueda IGDB →
  slug/carátula/ficha`, cacheado en BD. Las credenciales se leen del entorno o
  de `backend/.env`, nunca versionadas.

## Hoja de ruta

- **F0 — Cimientos** *(en curso)*: monorepo uv/pnpm, parser validado contra el
  volcado real, ingesta→SQLite, API núcleo (`/api/meta`, `/api/titles`,
  `/api/titles/{slug}`, `/api/sync`), frontend con layout y grid scrob-like.
- **F1 — Núcleo de datos**: snapshots y diffs entre volcados (añadidos/borrados/
  versiones), índice de títulos normalizado (`nombre_norm` para buscar igual que
  `productos.nombre_norm` de gamechecker), extensiones→formato/plataforma.
- **F2 — API completa**: paginación, filtros (bucket, letra, versión, tamaño),
  orden, detalle de título con árbol de versiones y ficheros, stats agregadas.
- **F3 — Frontend scrob-like**: home/biblioteca (grid de tarjetas), buscador
  global con live results, página de detalle de juego con sus versiones
  (equivalente a página de película/serie), modo oscuro/claro y acentos.
- **F4 — Metadatos IGDB (GamesDb)**: resolución de carátulas/descripciones,
  cache y backfill; tarjetas con póster real.
- **F5 — Tiempo real MEGAcmd**: runner de sync programado (y opcional
  `mega-sync`/estado), eventos SSE a la web (recarga de grid), estado del
  sincronizador en la UI (equivalente a `SyncStatus.astro` de scrob).
- **F6 — Paridad de funciones scrob**: listas personales, favoritos,
  "recientes", estadísticas de biblioteca, historial de snapshots, PWA/offline.

## Equivalencias scrob → aquí (para F3+)

| Scrob (referencia)              | AlucardiosDataBase                              |
| ------------------------------- | ----------------------------------------------- |
| Biblioteca movies/shows         | Grid de títulos del árbol MEGA (con carátula IGDB) |
| Página media (poster/cast)      | Detalle de título: versiones `B-ASE/U-PD/D-LC`, ficheros, tamaños |
| Buscador TMDB                   | Buscador sobre títulos del snapshot (+IGDB)     |
| Historial / visto               | Historial de snapshots/diffs (añadidos/borrados) |
| Stats                           | Stats: títulos, TiB, top franquicias, formatos  |
| SyncStatus / conexiones         | Panel de estado de MEGAcmd e ingesta            |

## Mapa del código (F0)

```
backend/app
├── config.py        Settings (rutas, DB, MEGAcmd, IGDB, CORS)
├── db.py            engine/session SQLAlchemy (SQLite WAL o DATABASE_URL)
├── models.py        Snapshot · Node · Title (SQLAlchemy 2.0 mapped)
├── schemas.py       Pydantic de API
├── parser.py        Parser streaming del volcado texto → árbol plano
├── ingest.py        CLI: fichero/volcado → snapshot atómico (idempotente)
├── library.py       Consultas de servicio (títulos, buckets, detalle)
├── megacmd.py       Wrapper MEGAcmd (localización, login/ls) — F0 base
├── igdb.py          Cliente IGDB opcional (metadatos) — F0 base
└── routers/         health.py · meta.py · library.py · sync.py
frontend/src
├── layouts/Base.astro   Shell scrob-like (nav, tema, footer)
├── components/          GameCard, BucketStrip, SearchBox…
├── pages/               index (biblioteca), game/[slug], …
└── lib/api.ts           cliente fetch tipado (puerto backend)
```
