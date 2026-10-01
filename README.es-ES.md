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
- **Colección retro aparte.** Un segundo in-share de MEGA con ROMs (arcade,
  consolas, micros) se indexa en **su propia base de datos** y se sirve en
  `/retro` con su propia API, sin mezclarse nunca con la biblioteca de Switch.
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

### Mantener la biblioteca al día (refresco del volcado + `backend-sync`)

`backend-sync` solo *aplica* diferencias: el volcado canónico lo genera una
sesión MEGAcmd viva en el host (`scripts/refrescar_volcado.py`), así que nada
dentro de los contenedores puede regenerarlo. Ese refresco se automatiza en el
host:

```bash
make volcado-auto      # refresca el volcado YA y aplica el escaneo incremental
make volcado-cron      # instala la entrada de cron (cada 6 h, idempotente)
make volcado-estado    # último resultado + cola del log + entrada de cron
make volcado-cron-off  # retira la entrada de cron
```

El pipeline es **de fallo rápido y ruidoso** a propósito: `scripts/autovolcado.sh`
sale con código != 0 si no hay sesión MEGA o si falla el refresco/escaneo (cron
avisa por correo y todo queda en `data/volcado.log`), y `backend-sync` sale con
código 3 cuando el volcado supera `ALUCARD_SYNC_MAX_EDAD_HORAS` (26 h) en vez de
repetir "sin cambios" para siempre. `GET /api/sync/status` expone
`dump_obsoleto`/`dump_age_hours` y la página `/novedades` muestra un aviso, para
que una biblioteca congelada se VEA en lugar de pasar desapercibida.

### Rotación semanal de credenciales (otra cuenta, misma biblioteca)

Las credenciales de MEGA rotan cada semana (cuentas distintas que montan el
**mismo share**). El pipeline está anclado al share, no a la cuenta:

```bash
make credenciales     # guarda MEGA_EMAIL/MEGA_PASSWORD de la semana (chmod 600)
# → ~/.config/alucard/mega.env  (o ALUCARD_MEGA_ENV, o MEGA_EMAIL en el entorno)
```

- Si la sesión activa es de otra cuenta, `scripts/lib/mega_session.sh` se
  re-loguea solo (login primero; si falla **restaura** la sesión previa y sale
  rc=4, así el host nunca se queda sin MEGAcmd).
- Antes de listar nada, `scripts/verificar_rotacion.py` hace un **pre-vuelo** en
  segundos (`mega-mount` + un `mega-ls` NO recursivo) y comprueba que la sesión
  activa monta el in-share del volcado vigente y que su raíz conserva los mismos
  buckets: si las credenciales de la semana montan OTRA biblioteca aborta con
  **rc=8** sin gastar minutos en `mega-ls -R -l` ni tocar el volcado. El veredicto
  se escribe en `data/estado_cuentas.json` (`ALUCARD_PREFLIGHT=0` lo desactiva) y
  lo publica `GET /api/sync/cuentas`, que es lo que usa `/novedades` para avisar
  cuando la cuenta de la semana no ve la biblioteca.
- **Failover guiado por la biblioteca (`make rotacion`)**: entrar en MEGA y *ver*
  la biblioteca son cosas distintas — una cuenta del pool puede entrar y montar
  otro share, así que quien decide es el pre-vuelo. Cuando la credencial de la
  semana pasa el pre-vuelo sin ver la biblioteca, `autovolcado.sh` prueba el pool
  (`~/.config/alucard/mega_cuentas.txt`, `ALUCARD_MEGA_CUENTAS`) cuenta por cuenta
  con ese mismo pre-vuelo y deja la sesión en la primera que **sí** la ve
  (`verificar_rotacion.py --elegir-cuenta`), de modo que el cron sigue refrescando
  en vez de fallar cada 6 h. Si ninguna cuenta del pool la ve, se **restaura** la
  credencial preferida y se aborta con rc=8 igual que antes.
  `ALUCARD_ROTACION=0` desactiva el failover y `ALUCARD_ROTACION_PERSISTIR=1`
  guarda además la cuenta elegida como credencial preferida (chmod 600, fuera del
  repo); ninguna contraseña llega al informe, al log ni a la API.
- `refrescar_volcado.py` aborta (rc=1, sin escribir nada) si el candidato pierde
  un sector que hoy trae archivos: unas credenciales sin acceso a la biblioteca
  no pueden vaciar el catálogo. `--permitir-sectores-perdidos` lo permite a
  propósito.
- `app.sync` hace diff por rutas y la etiqueta de sector sale del share
  (`INSHARE <dueño>:<carpeta>`), así que rotar la cuenta sin cambios reales da 0
  altas/bajas: ni "Novedades" fantasma ni re-enriquecido IGDB. `GET
  /api/sync/status` informa del `dump_fuente` estable junto a la `account`
  rotativa, y `/novedades` lo muestra.
- **Solo se indexa la biblioteca.** El volcado también trae los sectores de la
  CUENTA que lo generó (`CLOUD_DRIVE`, `INBOX`, `RUBBISH_BIN`), y esa nube
  personal cambia con la rotación semanal. `app.sync`/`app.ingest` se quedan solo
  con los sectores de biblioteca (`INSHARE …`): esos archivos no entran al
  catálogo, no aparecen en "Novedades" y no mueven los totales publicados. Cada
  escaneo dice cuánto se ha ignorado (`stats["ignorados_fuera_biblioteca"]`, al
  log y por consola) y el pre-vuelo publica cuántas entradas tiene la cuenta
  actual fuera de la biblioteca (`nube_propia` en `GET /api/sync/cuentas`, visible
  en `/novedades`). Una base de datos que ya tuviera ese ruido se limpia en el
  siguiente escaneo.
- **Renombrado del share (p. ej. `BCKP1` → `BCKP2`)**: cuando desaparece un share
  y aparece otro con contenido equivalente, `app.sync` detecta la rotación,
  remapea las rutas guardadas y reinicia los enlaces de descarga cacheados
  (`pendiente`) en vez de borrar y reconstruir el catálogo: sobreviven los
  `node_id`, los títulos y el IGDB, y "Novedades" solo lista lo realmente nuevo.
  Vuelve a indexar los enlaces contra el share nuevo con
  `./scripts/enlazar_descargas.sh` (host, reanudable).

## Colección retro (catálogo aparte)

El pool de cuentas de MEGA también trae una **segunda biblioteca independiente**:
ROMs retro (arcade, consolas, microordenadores) en **otro in-share**, montado por
otra cuenta del pool. Se sirve como **sección aparte** para que nunca contamine el
catálogo de Switch:

- **Su propio volcado y su propia BD.** `data/mega_retro_contenido_MEGAcmd.txt` se
  indexa en `data/retro.db` (`ALUCARD_RETRO_DUMP_PATH`, `ALUCARD_RETRO_DB_PATH`),
  nunca en `data/alucard.db`: `/api/meta`, `/api/titles` y `/novedades` siguen
  describiendo solo la biblioteca de Switch.
- **Su propia API y su página.** `/api/retro/meta|sistemas|titles|titles/{slug}|status`
  y `/retro` + `/retro/game/{slug}` (reutilizando `GameCard`).
- **Mismos datos de IGDB que el catálogo de Switch.** Los nombres de ROM traen
  ruido de dump (`Tomb Raider (USA).7z`, `(Rev 1)`, `[!]`) que hundía el matcher,
  así que `app.enrich` acepta `--coleccion retro` y lo recorta
  (`igdb.titulo_para_igdb_rom`) antes de preguntar a IGDB. El worker supervisado
  `backend-retro-enrich` (su BD, `--coleccion retro`) rellena carátula, nombre
  canónico y ficha completa, y `/retro/game/{slug}` los pinta con el MISMO
  componente compartido que la ficha de Switch (`components/FichaIGDB.astro`).
  `GET /api/retro/status` publica el progreso (`caratulas`, `enriquecidos`,
  `pendientes_enrich`, `sin_match`). El barrido va en paralelo (`--concurrencia`,
  def. 4; el throttle del conector pacea los arranques a ~3.3 req/s, por debajo
  del límite de 4 req/s de IGDB) y cada pasada registra su ritmo real en
  títulos/min, así que un volcado de 10k ROMs se ve avanzar con
  `docker compose logs -f backend-retro-enrich`.
- **Otro árbol.** El nivel 1 es el SISTEMA (`ARC N-64`, `ARC Mame2003`…) y el nivel
  2 los juegos; un juego puede ser un **archivo suelto** (MAME/Atari `.zip`) o una
  carpeta con sus variantes (`B-ASE`), y las carpetas-letra (`B/`, `#/`) son
  contenedores, no juegos. `app.ingest`/`app.sync` lo implementan con
  `--coleccion retro`.
- **Los sistemas se publican con su nombre OFICIAL.** Esa carpeta de nivel 1 es un
  código del volcado hecho a mano y es la identidad del contenido en MEGA, así que
  `titles.letter` lo conserva, pero ningún catálogo debería enseñar `ARC
  S3G4-Mega Drive-G3N3S1S`: `app.plataformas` (catálogo estático construido sobre
  `/v4/platforms` de IGDB) resuelve cada bucket al vuelo a `nombre` / `corto` /
  `igdb_id` / `igdb_slug` / `generacion` / `familia`, y todo payload que identifica
  un bucket añade un objeto `plataforma` junto al `letter` intacto
  (`/api/retro/sistemas`, `/api/retro/titles`, `/api/retro/titles/{slug}`, la
  exportación JSON y los equivalentes de Switch). Los chips y badges de `/retro`
  se leen *N64*, *Mega Drive*, *MAME*… y el filtro `sistema` acepta la clave
  canónica (`mega-drive`), el nombre oficial o el código antiguo del volcado, así
  que los enlaces viejos siguen funcionando. Un código que todavía no esté en el
  catálogo se muestra tal cual con `conocido=False` (nunca se inventa) y el chip lo
  avisa; `Sega NAOMI`, `Atomiswave` y `ScummVM` se publican con `igdb_id=None`
  porque IGDB no los tiene como plataforma.
- **El catálogo se lee por el nombre OFICIAL.** El título canónico de IGDB y su
  año de lanzamiento original viven en columnas propias (`igdb_name`,
  `igdb_name_norm`, `igdb_year`), mientras el nombre del fichero/carpeta de la ROM
  sigue en `name`: es lo que identifica el contenido en MEGA. `/retro` se titula,
  se busca (`q=Three Wonders` encuentra `3wonders.zip`) y se **ordena por ese
  nombre por defecto** (`sort=canonico`; `sort=year` ordena por época), enseñando
  el fichero ROM bajo la carátula (tarjetas, autosuggest, cabecera de la ficha y
  `<title>` de la página); `GET /api/retro/status` añade `con_nombre_oficial`. Las
  bases desplegadas reciben las columnas solas al arrancar
  (`app.db.migrar_esquema`) y `make enrich-retro-campos` (o `make enrich-campos`
  para Switch) las rellena desde las fichas ya guardadas, **sin llamar a IGDB**.
- **Refresco en el host (cron).** `scripts/volcado_retro.sh` (`make volcado-retro`)
  rota MEGAcmd a la cuenta que *de verdad ve* el in-share de ROMs
  (`verificar_rotacion.py --volcado … --elegir-cuenta`, guiado por biblioteca y no
  por login), refresca el volcado, **restaura siempre la sesión preferida de
  Switch** al salir (trap) y pide a la API el escaneo de su BD
  (`POST /api/retro/dump`). Se instala con `make volcado-retro-cron` (cada 6 h,
  desfasado 30 min del cron de Switch); `make volcado-retro-estado` muestra el
  último resultado y `make retro-status` el endpoint de frescura. El worker
  `backend-retro-sync` es la red de seguridad.
- **Aislamiento por construcción.** Todos los endpoints retro leen
  `app.state.engine_retro`, así que un error en una colección no puede tocar la otra.

Puesta en marcha rápida:

```bash
make retro-credenciales   # guarda la cuenta que ve el in-share de ROMs (chmod 600, fuera del repo)
make volcado-retro        # primer volcado + escaneo (crea data/retro.db)
make volcado-retro-cron   # mantenerlo fresco cada 6 h
```

`GET /api/retro/status` (`make retro-status`) informa de la frescura del volcado,
su `volcado_fuente` (el in-share), el nº de sistemas/juegos y un `aviso` para
mostrar en la UI cuando el volcado falta o está caducado.

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
| `ALUCARD_SYNC_MAX_EDAD_HORAS`        | Edad máxima del volcado antes de que el vigía falle (def. 26) |
| `ALUCARD_SYNC_MIN_FRACCION`          | Fracción mínima de archivos que debe conservar el volcado (def. 0.5) |
| `ALUCARD_RETRO_DUMP_PATH`            | Volcado de ROMs retro (def. `data/mega_retro_contenido_MEGAcmd.txt`) |
| `ALUCARD_RETRO_DB_PATH` / `..._DATABASE_URL` | BD de la colección retro (def. `data/retro.db`) |
| `PUBLIC_BACKEND_HOST` / `..._PORT`   | URL del backend horneada en el build web     |
| `BACKEND_PORT` / `FRONTEND_PORT`     | Puertos publicados en el host (Compose)      |

## Operaciones

El `Makefile` agrupa los flujos principales: `make enrich`, `make enrich-retro`,
`make enrich-campos`, `make enrich-retro-campos`,
`make sync`,
`make export`, `make catalog`, `make volcado`, `make volcado-auto`,
`make volcado-cron`, `make sync-status`, `make pre-vuelo`, `make rotacion`,
`make volcado-retro`, `make volcado-retro-cron`, `make volcado-retro-estado`,
`make retro-credenciales`, `make retro-status`, `make retro-sync`,
`make versiones`, `make versiones-daemon`, `make test`, `make lint` y
`make e2e`.

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

