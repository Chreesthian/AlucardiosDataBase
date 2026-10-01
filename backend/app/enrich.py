"""Enriquecimiento IGDB en dos fases (ficha COMPLETA por juego).

1) MATCH: resuelve el título MEGA → slug IGDB con `mejor_juego_ampliado`
   (variantes sin prefijos de serie → más cobertura, misma puerta de confianza).
2) FICHA COMPLETA: pide `ficha_detallada(slug)` (sinopsis, storyline, ratings,
   capturas, vídeos, desarrollador/editor, plataformas, géneros, similares…).

El payload se guarda versionado en `titles.igdb_json` (`ficha_v: 2`); los fallos
se marcan como probados (miss v2) y las filas de la fase anterior (v1) se
actualizan automáticamente. Reanudable e idempotente.

Fase 3) IDENTIDAD CANÓNICA: de cada ficha se materializan en columnas propias el
NOMBRE OFICIAL de IGDB (`igdb_name`, normalizado en `igdb_name_norm`) y el año del
lanzamiento original (`igdb_year`). El nombre del fichero/carpeta (la ROM, p. ej.
`After Burner.zip`) se conserva en `titles.name`: sirve para localizar el contenido
en MEGA, mientras que el catálogo se ordena, busca y muestra por el nombre
canónico. Esto no necesita red (`--campos` lo pone al día desde lo ya guardado).

Uso:
    uv run python -m app.enrich               # avanza todo lo pendiente/actualizable
    uv run python -m app.enrich --limit 50
    uv run python -m app.enrich --full        # ignora marcas y re-procesa todo
    uv run python -m app.enrich --campos      # nombre oficial/año sin tocar IGDB
    uv run python -m app.enrich --db ../data/retro.db --coleccion retro

Cada colección tiene SU PROPIA BD y su propio worker supervisado
(`backend-enrich` para el catálogo de Switch, `backend-retro-enrich` para las
ROMs): aquí solo cambia la BD (`--db`) y cómo se limpia el nombre antes de
buscar en IGDB (`--coleccion`, ver `_termino_de_busqueda`).

Rendimiento: `--concurrencia` (def. 4) solapa las peticiones IGDB (el throttle
del conector pacea los arranques a ~3.3 req/s, bajo el límite de 4 req/s de
IGDB) y el matcher v3 corta en cuanto hay identidad inequívoca, así que un
barrido de 10k ROMs pasa de ~26 a ~90-100 títulos/min.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .igdb import (
    IgdbConnector,
    IgdbNoConfigurado,
    ficha_desde_juego,
    titulo_para_igdb,
    titulo_para_igdb_rom,
)
from .ingest import COLECCION_RETRO, COLECCION_SWITCH, COLECCIONES
from .library import current_snapshot
from .models import Title
from .normalize import normalize

log = logging.getLogger("alucard.enrich")

FICHA_V = 2

ProcesadorFicha = Callable[[str, dict[str, Any] | None], dict[str, Any] | None]


def _parse(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return cast("dict[str, Any]", data)


def version(payload: dict[str, Any] | str | None) -> int:
    if isinstance(payload, str):
        payload = _parse(payload)
    if not payload:
        return 0
    return int(payload.get("ficha_v") or 0)


def necesita_trabajo(payload: dict[str, Any] | None) -> bool:
    """True si la fila requiere match o ficha completa (v0/v1 o miss antiguo)."""
    v = version(payload)
    if v == 0:
        return True
    # v1: puede ser match básico (le falta ficha completa) o miss antiguo.
    return v < FICHA_V


def listar_trabajo(session: Session, snapshot_id: int) -> list[Title]:
    """Filas a procesar: sin resolver, o resueltas en una fase anterior."""
    rows: list[Title] = []
    for t in session.execute(
        select(Title).where(Title.snapshot_id == snapshot_id).order_by(Title.id.asc())
    ).scalars():
        if necesita_trabajo(_parse(t.igdb_json)):
            rows.append(t)
    return rows


def _payload_miss() -> dict[str, Any]:
    return {"ficha_v": FICHA_V, "miss": True}


def _anio_de(fecha: Any) -> int | None:
    """Año del lanzamiento original a partir de la fecha ISO de la ficha (`YYYY-MM-DD`)."""
    if isinstance(fecha, str) and len(fecha) >= 4 and fecha[:4].isdigit():
        return int(fecha[:4])
    return None


def campos_canonicos(
    payload: dict[str, Any] | None,
) -> tuple[str | None, str | None, int | None]:
    """Identidad OFICIAL (nombre canónico, normalizado y año) de una ficha guardada.

    IGDB da a cada juego un título canónico (`nombre_oficial`) y una fecha de
    lanzamiento original. Se materializan en columnas propias (`igdb_name`,
    `igdb_name_norm`, `igdb_year`) porque el catálogo ordena y busca por ellas en
    SQL; el nombre del fichero/carpeta (la ROM) se conserva en `titles.name`.
    Un `miss` no tiene identidad oficial: devuelve `(None, None, None)`.
    """
    if not payload or payload.get("miss"):
        return None, None, None
    nombre = payload.get("nombre_oficial")
    if not isinstance(nombre, str) or not nombre.strip():
        return None, None, None
    nombre = " ".join(nombre.split())
    return nombre, normalize(nombre), _anio_de(payload.get("fecha_lanzamiento"))


def _termino_de_busqueda(nombre: str, coleccion: str) -> str:
    """Nombre del título → término de búsqueda IGDB según SU colección.

    - `switch`: el nombre de la carpeta de MEGA ya es el título real.
    - `retro`: nombre de ROM con ruido de dump (`Tomb Raider (USA).7z`) →
      `igdb.titulo_para_igdb_rom` lo recorta antes de buscar. Sin esto, media
      colección se queda sin ficha por región/revisión/extensión.
    """
    if coleccion == COLECCION_RETRO:
        return titulo_para_igdb_rom(nombre)
    return titulo_para_igdb(nombre)


def procesar_con_connector(
    connector: IgdbConnector, *, coleccion: str = COLECCION_SWITCH
) -> ProcesadorFicha:
    """Devuelve `procesar(nombre, payload_previo) -> payload nuevo|None`.

    None indica que el título ya está al día (v2) y no se toca.
    """

    def procesar(
        nombre: str,
        previo: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        v = version(previo)
        if v >= FICHA_V:
            return None
        slug_previo: str | None = previo.get("slug") if previo else None

        if slug_previo:  # fase v1 match básico → solo falta ficha completa
            detalle = connector.ficha_detallada(str(slug_previo))
            if detalle:
                return detalle
            # Fallo puntual de IGDB: no marcar miss (conserva portada); se
            # reintentará en la siguiente pasada.
            return None

        limpio = _termino_de_busqueda(nombre, coleccion)
        if not limpio:
            return _payload_miss()
        juego = connector.mejor_juego_v3(limpio, nombre=nombre)
        if juego is None or not juego.slug:
            return _payload_miss()

        detalle = connector.ficha_detallada(juego.slug)
        if detalle is None:
            # IGDB lo busca pero no da ficha detallada: guardamos la básica v1
            # para no perder la carátula (se reintentará en otra pasada).
            basica = ficha_desde_juego(juego)
            basica["ficha_v"] = 1
            return basica
        return detalle

    return procesar


def aplicar(titulo: Title, payload: dict[str, Any]) -> None:
    """Vuelca el payload v2 en los campos de la fila (sin commit)."""
    titulo.igdb_json = json.dumps(payload, ensure_ascii=False)
    titulo.igdb_slug = payload.get("slug")
    titulo.igdb_cover = payload.get("caratula")
    nombre, nombre_norm, anio = campos_canonicos(payload)
    titulo.igdb_name = nombre
    titulo.igdb_name_norm = nombre_norm
    titulo.igdb_year = anio
    if payload.get("miss"):
        titulo.igdb_slug = None
        titulo.igdb_cover = None


def _poner_al_dia(session: Session, snapshot_id: int) -> dict[str, int]:
    """Rellena SIN RED los campos derivados de la ficha YA guardada (sin commit).

    Dos casos: portadas que quedaron vacías y la identidad canónica de las bases
    que se enriquecieron antes de que existieran `igdb_name`/`igdb_year`. Corrige
    también valores obsoletos (p. ej. tras un re-match o un `miss`).
    """
    filas = list(session.execute(select(Title).where(Title.snapshot_id == snapshot_id)).scalars())
    portadas = canonicos = 0
    for t in filas:
        p = _parse(t.igdb_json)
        if t.igdb_cover is None and p and not p.get("miss") and p.get("caratula"):
            t.igdb_cover = p["caratula"]
            portadas += 1
        campos = campos_canonicos(p)
        if (t.igdb_name, t.igdb_name_norm, t.igdb_year) != campos:
            t.igdb_name, t.igdb_name_norm, t.igdb_year = campos
            canonicos += 1
    return {"filas": len(filas), "portadas": portadas, "canonicos": canonicos}


def rellenar_campos_canonicos(engine: Engine) -> dict[str, int]:
    """Pone al día la identidad canónica y las portadas de una colección entera.

    Es `_poner_al_dia` sobre una sesión propia y SIN conectar con IGDB: sirve para
    actualizar de golpe las bases ya enriquecidas (`app.enrich --campos`) cuando
    se añaden campos derivados, sin gastar cuota ni re-resolver nada.
    """
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return {"filas": 0, "portadas": 0, "canonicos": 0}
        stats = _poner_al_dia(session, snap.id)
        session.commit()
    return stats


def _log_progreso(stats: dict[str, Any], procesadas: int, inicio: float) -> None:
    """Progreso con ritmo real (títulos/min) para ver el avance de la pasada."""
    minutos = max((time.monotonic() - inicio) / 60.0, 1e-6)
    log.info(
        "progreso %d/%d (ok=%d detalle=%d · %.0f títulos/min)",
        procesadas,
        stats["total"],
        stats["ok"],
        stats["detalle"],
        procesadas / minutos,
    )


def run(
    engine: Engine,
    *,
    limit: int | None = None,
    full: bool = False,
    procesar: ProcesadorFicha | None = None,
    connector: IgdbConnector | None = None,
    coleccion: str = COLECCION_SWITCH,
    concurrencia: int = 4,
) -> dict[str, Any]:
    """Enriquece títulos (match + ficha completa). Devuelve contadores.

    `coleccion` solo cambia la limpieza del nombre antes de buscar en IGDB
    (`_termino_de_busqueda`): el catálogo de Switch y las ROMs retro viven en BD
    distintas y se enriquecen con workers distintos.

    `concurrencia` son las peticiones IGDB en vuelo: el throttle del conector
    pacea los arranques (0.3 s → ~3.3 req/s, bajo el límite de 4 req/s de IGDB)
    mientras varias van en paralelo, así que el ritmo sube sin arriesgar un 429.
    Solo se paraleliza la RED: la sesión ORM se toca únicamente en este hilo.
    """
    stats: dict[str, Any] = {
        "ok": 0,
        "detalle": 0,
        "miss": 0,
        "error": 0,
        "total": 0,
        "limit": limit,
        "cobertura": 0,
        "con_detalle": 0,
    }

    if procesar is None:
        if connector is None:
            connector = IgdbConnector()
        if not connector.configurado():
            raise IgdbNoConfigurado(
                "IGDB no configurado: define IGDB_CLIENT_ID/IGDB_CLIENT_SECRET "
                "en backend/.env (crea un cliente en dev.twitch.tv y copia las claves)"
            )
        procesar = procesar_con_connector(connector, coleccion=coleccion)

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            stats["sin_snapshot"] = True
            return stats
        filas = list(
            session.execute(
                select(Title).where(Title.snapshot_id == snap.id).order_by(Title.id.asc())
            ).scalars()
        )
        trabajo = filas if full else listar_trabajo(session, snap.id)
        stats["total"] = len(trabajo)

        procesadas = 0
        inicio_pasada = time.monotonic()
        # La RED va en paralelo (el throttle del conector pacea los arranques);
        # la BD se toca SOLO en este hilo, dentro de la sesión ORM.
        hilos = max(1, int(concurrencia or 1))
        lote = hilos * 3
        with ThreadPoolExecutor(max_workers=hilos) as pool:
            for inicio in range(0, len(trabajo), lote):
                bloque = trabajo[inicio : inicio + lote]
                if limit is not None:
                    restante = limit - procesadas
                    if restante <= 0:
                        break
                    bloque = bloque[:restante]
                # `previo` se lee aquí (hilo principal) para que los hilos de red
                # nunca toquen la sesión ORM.
                pendientes = [
                    (t, pool.submit(procesar, t.name, _parse(t.igdb_json))) for t in bloque
                ]
                for titulo, futuro in pendientes:
                    try:
                        nuevo = futuro.result()
                    except IgdbNoConfigurado:
                        for _, f in pendientes:
                            f.cancel()
                        raise
                    except Exception as exc:  # noqa: BLE001 — de red; no marcar
                        log.warning("error procesando %r: %s", titulo.name, exc)
                        stats["error"] += 1
                        procesadas += 1
                        if procesadas % 25 == 0:
                            session.commit()
                            _log_progreso(stats, procesadas, inicio_pasada)
                        continue
                    if nuevo is None:
                        continue  # ya v2, no se toca
                    aplicar(titulo, nuevo)
                    if nuevo.get("miss"):
                        stats["miss"] += 1
                    else:
                        stats["ok"] += 1
                        if nuevo.get("ficha_v", 0) >= FICHA_V:
                            stats["detalle"] += 1
                    procesadas += 1
                    if procesadas % 25 == 0:
                        session.commit()
                        _log_progreso(stats, procesadas, inicio_pasada)
        session.commit()
        stats["segundos"] = round(time.monotonic() - inicio_pasada, 1)
        stats["por_min"] = round(procesadas * 60 / max(stats["segundos"], 1e-6), 1)

        # Puesta al día SIN RED de lo derivado de la ficha guardada: portadas
        # vacías y campos canónicos (nombre oficial/año) de las bases enriquecidas
        # antes de que esos campos existieran. `--campos` hace esto solo.
        al_dia = _poner_al_dia(session, snap.id)
        if al_dia["portadas"] or al_dia["canonicos"]:
            session.commit()
            log.info(
                "campos al día sin red: portadas=%d canonicos=%d",
                al_dia["portadas"],
                al_dia["canonicos"],
            )

        # Métricas finales sobre TODA la biblioteca del snapshot.
        total_rows = list(
            session.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars()
        )
        stats["cobertura"] = sum(1 for t in total_rows if t.igdb_cover)
        stats["con_nombre_oficial"] = sum(1 for t in total_rows if t.igdb_name)
        con_detalle = 0
        for t in total_rows:
            p = _parse(t.igdb_json)
            if p is not None and not p.get("miss") and version(p) >= FICHA_V:
                con_detalle += 1
        stats["con_detalle"] = con_detalle
    if connector is not None:
        connector.close()
    return stats


def daemon(
    engine: Engine,
    *,
    sleep_seg: int = 60,
    limit: int | None = None,
    full: bool = False,
    coleccion: str = COLECCION_SWITCH,
    concurrencia: int = 4,
) -> None:
    """Worker persistente de enriquecimiento (bucle supervisado).

    Pensado para correr bajo `docker compose` (restart: unless-stopped). Cada
    pasada es idempotente y solo toca lo pendiente/actualizable; así, los
    títulos nuevos que lleguen por sincronización incremental reciben portada y
    ficha automáticamente, y los fallos puntuales de red se reintentan solos.
    """
    log.info(
        "enrich worker iniciado (daemon, coleccion=%s, sleep=%ss, concurrencia=%s)",
        coleccion,
        sleep_seg,
        concurrencia,
    )
    while True:
        try:
            stats = run(
                engine,
                limit=limit,
                full=full,
                coleccion=coleccion,
                concurrencia=concurrencia,
            )
            log.info("pasada completa: %s", stats)
        except IgdbNoConfigurado as exc:
            log.warning("IGDB no configurado (%s); reintento en %ss", exc, sleep_seg)
        except KeyboardInterrupt:
            log.info("detenido por KeyboardInterrupt")
            return
        except Exception:
            log.exception("error inesperado en pasada; reintento en %ss", sleep_seg)
        time.sleep(sleep_seg)


def _make_engine(db_arg: str | None = None) -> Engine:
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def _limpiar_igdb(t: Title) -> None:
    """Borra el estado IGDB de una fila: payload e identidad materializada.

    Al vaciar la ficha hay que vaciar también `igdb_name`/`igdb_year`: si no,
    quedaría un nombre oficial "colgado" de un match que se va a rehacer.
    """
    t.igdb_json = None
    t.igdb_slug = None
    t.igdb_cover = None
    t.igdb_name = None
    t.igdb_name_norm = None
    t.igdb_year = None


def limpiar_para_reprocesar(engine: Engine, fragmento: str) -> int:
    """Deja sin resolver los títulos cuyo nombre contiene `fragmento`
    (para re-hacer su match con la lógica mejorada). Devuelve nº de filas."""
    from .library import current_snapshot

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return 0
        rows = (
            session.execute(
                select(Title).where(
                    Title.snapshot_id == snap.id,
                    Title.name.contains(fragmento),
                )
            )
            .scalars()
            .all()
        )
        for t in rows:
            _limpiar_igdb(t)
        session.commit()
        return len(rows)


def limpiar_todo(engine: Engine) -> int:
    """Limpia el estado IGDB de TODOS los títulos (re-resolución global)."""
    from .library import current_snapshot

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return 0
        rows = session.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars().all()
        for t in rows:
            _limpiar_igdb(t)
        session.commit()
        return len(rows)


def refrescar_extra(
    engine: Engine, *, limite: int | None = None, slugs: list[str] | None = None
) -> dict[str, Any]:
    """Re-descarga la ficha IGDB ampliada (lanzamientos, enlaces, idiomas,
    clasificaciones…) de las fichas ya guardadas (idempotente y reanudable).

    - Sin `slugs`: actualiza los títulos v2 que aún no tienen los campos extra.
    - Con `slugs`: fuerza la actualización de esos slugs concretos.
    Devuelve contadores; los títulos que sigan sin extra se reintentan en otra
    ejecución (no se marcan como fallidos).
    """
    stats: dict[str, Any] = {"ok": 0, "sin_detalle": 0, "error": 0, "total": 0, "repetidos": 0}
    connector = IgdbConnector()
    try:
        if not connector.configurado():
            raise IgdbNoConfigurado("IGDB no configurado: define IGDB_CLIENT_ID/IGDB_CLIENT_SECRET")
        with Session(engine) as session:
            snap = current_snapshot(session)
            if snap is None:
                return stats
            filas = list(
                session.execute(
                    select(Title).where(Title.snapshot_id == snap.id, Title.igdb_slug.is_not(None))
                ).scalars()
            )
            pendientes: list[Title] = []
            for t in filas:
                p = _parse(t.igdb_json)
                if not p or p.get("miss") or version(p) < FICHA_V:
                    continue
                if slugs is not None and t.slug not in slugs:
                    continue
                if slugs is None and "lanzamientos" in p and p.get("hero_imagen"):
                    continue  # ya tiene la ficha ampliada (con hero artwork)
                pendientes.append(t)
            stats["total"] = len(pendientes)
            if limite is not None:
                pendientes = pendientes[:limite]
            for t in pendientes:
                try:
                    detalle = connector.ficha_detallada(t.igdb_slug or "")
                    if detalle:
                        aplicar(t, detalle)
                        stats["ok"] += 1
                    else:
                        stats["sin_detalle"] += 1
                except Exception as exc:  # noqa: BLE001 — red; reintento después
                    log.warning("error refrescando %r: %s", t.slug, exc)
                    stats["error"] += 1
                stats["repetidos"] += 1
                if stats["repetidos"] % 25 == 0:
                    session.commit()
                    log.info(
                        "refresco %d/%d (ok=%d)", stats["repetidos"], stats["total"], stats["ok"]
                    )
            session.commit()
    finally:
        connector.close()
    return stats


def limpiar_misses(engine: Engine) -> int:
    """Deja sin resolver SOLO los títulos marcados `miss` (reintento matcher v3).

    Los títulos ya resueltos (ficha v2) NO se tocan: la recuperación es
    quirúrgica y no re-golpea IGDB con lo ya correcto.
    """
    from .library import current_snapshot

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return 0
        n = 0
        for t in session.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars():
            payload = _parse(t.igdb_json)
            if payload and payload.get("miss"):
                _limpiar_igdb(t)
                n += 1
        session.commit()
        return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Enriquece títulos con la ficha IGDB completa")
    ap.add_argument("--db", default=None, help="Ruta SQLite")
    ap.add_argument(
        "--coleccion",
        choices=list(COLECCIONES),
        default=COLECCION_SWITCH,
        help="Colección a enriquecer (def. switch). 'retro' recorta el ruido de "
        "los nombres de ROM (región/revisión/extensión) antes de buscar en IGDB",
    )
    ap.add_argument("--limit", type=int, default=None, help="Máx. títulos")
    ap.add_argument(
        "--concurrencia",
        type=int,
        default=4,
        metavar="N",
        help="Peticiones IGDB en paralelo (def. 4). El throttle pacea los "
        "arranques a ~3.3 req/s, bajo el límite de 4 req/s de IGDB",
    )
    ap.add_argument("--full", action="store_true", help="Re-procesar todo (ignora marcas)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument(
        "--reprocesar",
        metavar="TEXTO",
        default=None,
        help="Limpia y re-resuelve títulos cuyo nombre contiene TEXTO",
    )
    ap.add_argument(
        "--miss",
        action="store_true",
        help="Reintenta SOLO los títulos marcados 'miss' (matcher v3)",
    )
    ap.add_argument(
        "--campos",
        action="store_true",
        help="Pone al día (SIN red) el nombre oficial/año y las portadas desde la "
        "ficha ya guardada: útil tras añadir campos derivados",
    )
    ap.add_argument(
        "--refrescar",
        type=int,
        default=None,
        metavar="N",
        help="Re-descarga fichas IGDB ampliadas de hasta N títulos "
        "(sin extra: lanzamientos/enlaces/idiomas…)",
    )
    ap.add_argument(
        "--slugs", default=None, help="Slugs concretos a refrescar (separados por coma)"
    )
    ap.add_argument(
        "--daemon", action="store_true", help="Modo worker: ejecuta pasadas en bucle (supervisado)"
    )
    ap.add_argument(
        "--sleep", type=int, default=60, help="Segundos entre pasadas en modo --daemon (def. 60)"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    # `httpx` loguea la URL completa de cada petición a nivel INFO y el token de
    # Twitch viaja en el query string (`…&client_secret=…`): sin esto el secreto
    # acaba en `docker compose logs`. El progreso útil ya lo imprime este módulo.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    engine = _make_engine(args.db)
    if args.reprocesar:
        n = limpiar_para_reprocesar(engine, args.reprocesar)
        print(f"Reprocesando {n} título(s) que contienen: {args.reprocesar}")
    if args.full:
        n = limpiar_todo(engine)
        print(f"Re-resolución GLOBAL: limpiados {n} títulos (match desde cero).")

    if args.miss:
        n = limpiar_misses(engine)
        print(f"Reintento v3: {n} título(s) 'miss' limpios para re-resolver.")

    if args.campos:
        res = rellenar_campos_canonicos(engine)
        print(
            f"Campos canónicos al día (sin red): {res['canonicos']} de {res['filas']} "
            f"título(s) · {res['portadas']} portada(s) rellenada(s)."
        )
        if not args.daemon:
            return

    if args.refrescar is not None or args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None
        stats = refrescar_extra(engine, limite=args.refrescar, slugs=slugs)
        print(
            f"Refresco fichas ampliadas: ok={stats['ok']} · "
            f"sin_detalle={stats['sin_detalle']} · errores={stats['error']} · "
            f"total={stats['total']}"
        )
        if not args.daemon:
            return

    if args.daemon:
        try:
            daemon(
                engine,
                sleep_seg=args.sleep,
                limit=args.limit,
                full=args.full,
                coleccion=args.coleccion,
                concurrencia=args.concurrencia,
            )
        except KeyboardInterrupt:
            print("Worker de enriquecimiento detenido.")
        return

    try:
        stats = run(
            engine,
            limit=args.limit,
            full=args.full,
            coleccion=args.coleccion,
            concurrencia=args.concurrencia,
        )
    except IgdbNoConfigurado as exc:
        raise SystemExit(f"⚠ {exc}") from exc
    print(
        f"Procesado ({args.coleccion}): match_ok={stats['ok']} · "
        f"detalle_completo={stats['detalle']} · "
        f"sin_match={stats['miss']} · errores={stats['error']} · total={stats['total']} · "
        f"{stats['segundos']}s ({stats['por_min']} títulos/min)"
    )
    print(
        f"Colección completa: con_caratula={stats['cobertura']} · "
        f"con_nombre_oficial={stats['con_nombre_oficial']} · "
        f"con_ficha_completa={stats['con_detalle']}"
    )


if __name__ == "__main__":
    main()
