"""Enriquecimiento IGDB en dos fases (ficha COMPLETA por juego).

1) MATCH: resuelve el título MEGA → slug IGDB con `mejor_juego_ampliado`
   (variantes sin prefijos de serie → más cobertura, misma puerta de confianza).
2) FICHA COMPLETA: pide `ficha_detallada(slug)` (sinopsis, storyline, ratings,
   capturas, vídeos, desarrollador/editor, plataformas, géneros, similares…).

El payload se guarda versionado en `titles.igdb_json` (`ficha_v: 2`); los fallos
se marcan como probados (miss v2) y las filas de la fase anterior (v1) se
actualizan automáticamente. Reanudable e idempotente.

Uso:
    uv run python -m app.enrich               # avanza todo lo pendiente/actualizable
    uv run python -m app.enrich --limit 50
    uv run python -m app.enrich --full        # ignora marcas y re-procesa todo
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .igdb import (
    IgdbConnector,
    IgdbNoConfigurado,
    ficha_desde_juego,
    titulo_para_igdb,
)
from .library import current_snapshot
from .models import Title

log = logging.getLogger("alucard.enrich")

FICHA_V = 2


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def version(payload: dict | str | None) -> int:
    if isinstance(payload, str):
        payload = _parse(payload)
    if not payload:
        return 0
    return int(payload.get("ficha_v") or 0)


def necesita_trabajo(payload: dict | None) -> bool:
    """True si la fila requiere match o ficha completa (v0/v1 o miss antiguo)."""
    v = version(payload)
    if v == 0:
        return True
    if v >= FICHA_V:
        return False
    # v1: puede ser match básico (le falta ficha completa) o miss antiguo.
    return True


def listar_trabajo(session: Session, snapshot_id: int) -> list[Title]:
    """Filas a procesar: sin resolver, o resueltas en una fase anterior."""
    rows = []
    for t in session.execute(
        select(Title).where(Title.snapshot_id == snapshot_id).order_by(Title.id.asc())
    ).scalars():
        if necesita_trabajo(_parse(t.igdb_json)):
            rows.append(t)
    return rows


def _payload_miss() -> dict:
    return {"ficha_v": FICHA_V, "miss": True}


def procesar_con_connector(connector: IgdbConnector):
    """Devuelve `procesar(nombre, payload_previo) -> payload nuevo|None`.

    None indica que el título ya está al día (v2) y no se toca.
    """

    def procesar(nombre: str, previo: dict | None):
        v = version(previo)
        if v >= FICHA_V:
            return None
        slug_previo = (previo or {}).get("slug")

        if slug_previo:  # fase v1 match básico → solo falta ficha completa
            detalle = connector.ficha_detallada(str(slug_previo))
            if detalle:
                return detalle
            # Fallo puntual de IGDB: no marcar miss (conserva portada); se
            # reintentará en la siguiente pasada.
            return None

        limpio = titulo_para_igdb(nombre)
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


def aplicar(titulo: Title, payload: dict) -> None:
    """Vuelca el payload v2 en los campos de la fila (sin commit)."""
    titulo.igdb_json = json.dumps(payload, ensure_ascii=False)
    titulo.igdb_slug = payload.get("slug")
    titulo.igdb_cover = payload.get("caratula")
    if payload.get("miss"):
        titulo.igdb_slug = None
        titulo.igdb_cover = None


def run(engine, *, limit: int | None = None, full: bool = False,
        procesar=None, connector: IgdbConnector | None = None) -> dict:
    """Enriquece títulos (match + ficha completa). Devuelve contadores."""
    stats = {"ok": 0, "detalle": 0, "miss": 0, "error": 0, "total": 0,
             "limit": limit, "cobertura": 0, "con_detalle": 0}

    if procesar is None:
        if connector is None:
            connector = IgdbConnector()
        if not connector.configurado():
            raise IgdbNoConfigurado(
                "IGDB no configurado: define IGDB_CLIENT_ID/IGDB_CLIENT_SECRET "
                "en backend/.env (crea un cliente en dev.twitch.tv y copia las claves)"
            )
        procesar = procesar_con_connector(connector)

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            stats["sin_snapshot"] = True
            return stats
        filas = list(session.execute(
            select(Title).where(Title.snapshot_id == snap.id).order_by(Title.id.asc())
        ).scalars())
        trabajo = filas if full else listar_trabajo(session, snap.id)
        stats["total"] = len(trabajo)

        procesadas = 0
        for titulo in trabajo:
            if limit is not None and procesadas >= limit:
                break
            try:
                previo = _parse(titulo.igdb_json)
                nuevo = procesar(titulo.name, previo)
                if nuevo is None:
                    continue  # ya v2, no se toca
                aplicar(titulo, nuevo)
                if nuevo.get("miss"):
                    stats["miss"] += 1
                else:
                    stats["ok"] += 1
                    if nuevo.get("ficha_v", 0) >= FICHA_V:
                        stats["detalle"] += 1
            except IgdbNoConfigurado:
                raise
            except Exception as exc:  # noqa: BLE001 — de red; no marcar
                log.warning("error procesando %r: %s", titulo.name, exc)
                stats["error"] += 1
            procesadas += 1
            if procesadas % 25 == 0:
                session.commit()
                log.info("progreso %d/%d (ok=%d detalle=%d)", procesadas,
                         stats["total"], stats["ok"], stats["detalle"])
        session.commit()

        # Portadas rezagadas: si la ficha v2 trae 'caratula' pero la columna
        # quedó vacía, la rellenamos (sin red) antes de las métricas.
        total_rows = list(session.execute(
            select(Title).where(Title.snapshot_id == snap.id)
        ).scalars())
        n_portadas = 0
        for t in total_rows:
            p = _parse(t.igdb_json)
            if t.igdb_cover is None and p and not p.get("miss") and p.get("caratula"):
                t.igdb_cover = p["caratula"]
                n_portadas += 1
        if n_portadas:
            session.commit()
            log.info("portadas rezagadas rellenadas: %d", n_portadas)

        # Métricas finales sobre TODA la biblioteca del snapshot.
        stats["cobertura"] = sum(1 for t in total_rows if t.igdb_cover)
        stats["con_detalle"] = sum(
            1 for t in total_rows if version(_parse(t.igdb_json)) >= FICHA_V
            and not (_parse(t.igdb_json) or {}).get("miss")
        )
    if connector is not None:
        connector.close()
    return stats


def daemon(engine, *, sleep_seg: int = 60, limit: int | None = None,
           full: bool = False) -> None:
    """Worker persistente de enriquecimiento (bucle supervisado).

    Pensado para correr bajo `docker compose` (restart: unless-stopped). Cada
    pasada es idempotente y solo toca lo pendiente/actualizable; así, los
    títulos nuevos que lleguen por sincronización incremental reciben portada y
    ficha automáticamente, y los fallos puntuales de red se reintentan solos.
    """
    log.info("enrich worker iniciado (daemon, sleep=%ss)", sleep_seg)
    while True:
        try:
            stats = run(engine, limit=limit, full=full)
            log.info("pasada completa: %s", stats)
        except IgdbNoConfigurado as exc:
            log.warning("IGDB no configurado (%s); reintento en %ss", exc, sleep_seg)
        except KeyboardInterrupt:
            log.info("detenido por KeyboardInterrupt")
            return
        except Exception:
            log.exception("error inesperado en pasada; reintento en %ss", sleep_seg)
        time.sleep(sleep_seg)


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def limpiar_para_reprocesar(engine, fragmento: str) -> int:
    """Deja sin resolver los títulos cuyo nombre contiene `fragmento`
    (para re-hacer su match con la lógica mejorada). Devuelve nº de filas."""
    from .library import current_snapshot
    from .models import Snapshot

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return 0
        rows = session.execute(
            select(Title).where(
                Title.snapshot_id == snap.id,
                Title.name.contains(fragmento),
            )
        ).scalars().all()
        for t in rows:
            t.igdb_json = None
            t.igdb_slug = None
            t.igdb_cover = None
        session.commit()
        return len(rows)


def limpiar_todo(engine) -> int:
    """Limpia el estado IGDB de TODOS los títulos (re-resolución global)."""
    from .library import current_snapshot
    from .models import Snapshot

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return 0
        rows = session.execute(
            select(Title).where(Title.snapshot_id == snap.id)
        ).scalars().all()
        for t in rows:
            t.igdb_json = None
            t.igdb_slug = None
            t.igdb_cover = None
        session.commit()
        return len(rows)


def refrescar_extra(engine, *, limite: int | None = None,
                    slugs: list[str] | None = None) -> dict:
    """Re-descarga la ficha IGDB ampliada (lanzamientos, enlaces, idiomas,
    clasificaciones…) de las fichas ya guardadas (idempotente y reanudable).

    - Sin `slugs`: actualiza los títulos v2 que aún no tienen los campos extra.
    - Con `slugs`: fuerza la actualización de esos slugs concretos.
    Devuelve contadores; los títulos que sigan sin extra se reintentan en otra
    ejecución (no se marcan como fallidos).
    """
    stats = {"ok": 0, "sin_detalle": 0, "error": 0, "total": 0, "repetidos": 0}
    connector = IgdbConnector()
    try:
        if not connector.configurado():
            raise IgdbNoConfigurado(
                "IGDB no configurado: define IGDB_CLIENT_ID/IGDB_CLIENT_SECRET"
            )
        with Session(engine) as session:
            snap = current_snapshot(session)
            if snap is None:
                return stats
            filas = list(session.execute(
                select(Title).where(
                    Title.snapshot_id == snap.id, Title.igdb_slug.is_not(None)
                )
            ).scalars())
            pendientes = []
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
                    log.info("refresco %d/%d (ok=%d)", stats["repetidos"],
                             stats["total"], stats["ok"])
            session.commit()
    finally:
        connector.close()
    return stats


def limpiar_misses(engine) -> int:
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
        for t in session.execute(
            select(Title).where(Title.snapshot_id == snap.id)
        ).scalars():
            payload = _parse(t.igdb_json)
            if payload and payload.get("miss"):
                t.igdb_json = None
                t.igdb_slug = None
                t.igdb_cover = None
                n += 1
        session.commit()
        return n


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enriquece títulos con la ficha IGDB completa"
    )
    ap.add_argument("--db", default=None, help="Ruta SQLite")
    ap.add_argument("--limit", type=int, default=None, help="Máx. títulos")
    ap.add_argument("--full", action="store_true", help="Re-procesar todo (ignora marcas)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--reprocesar", metavar="TEXTO", default=None,
                    help="Limpia y re-resuelve títulos cuyo nombre contiene TEXTO")
    ap.add_argument("--miss", action="store_true",
                    help="Reintenta SOLO los títulos marcados 'miss' (matcher v3)")
    ap.add_argument("--refrescar", type=int, default=None, metavar="N",
                    help="Re-descarga fichas IGDB ampliadas de hasta N títulos "
                         "(sin extra: lanzamientos/enlaces/idiomas…)")
    ap.add_argument("--slugs", default=None,
                    help="Slugs concretos a refrescar (separados por coma)")
    ap.add_argument("--daemon", action="store_true",
                    help="Modo worker: ejecuta pasadas en bucle (supervisado)")
    ap.add_argument("--sleep", type=int, default=60,
                    help="Segundos entre pasadas en modo --daemon (def. 60)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

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

    if args.refrescar is not None or args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()] \
            if args.slugs else None
        stats = refrescar_extra(engine, limite=args.refrescar, slugs=slugs)
        print(f"Refresco fichas ampliadas: ok={stats['ok']} · "
              f"sin_detalle={stats['sin_detalle']} · errores={stats['error']} · "
              f"total={stats['total']}")
        if not args.daemon:
            return

    if args.daemon:
        try:
            daemon(engine, sleep_seg=args.sleep, limit=args.limit, full=args.full)
        except KeyboardInterrupt:
            print("Worker de enriquecimiento detenido.")
        return

    try:
        stats = run(engine, limit=args.limit, full=args.full)
    except IgdbNoConfigurado as exc:
        raise SystemExit(f"⚠ {exc}") from exc
    print(
        f"Procesado: match_ok={stats['ok']} · detalle_completo={stats['detalle']} · "
        f"sin_match={stats['miss']} · errores={stats['error']} · total={stats['total']}"
    )
    print(
        f"Biblioteca completa: con_caratula={stats['cobertura']} · "
        f"con_ficha_completa={stats['con_detalle']}"
    )


if __name__ == "__main__":
    main()
