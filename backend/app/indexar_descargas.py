"""Indexador de enlaces de descarga (rutas → enlace MEGA) para la web.

Guarda profesionalmente, por cada ruta de la biblioteca, su enlace público de
descarga en la tabla `downloads` (persistente + exportable a JSON consumible
por la web). Estrategia:
  1. Registra TODAS las rutas objetivo como `pendiente` (sin red, rápido).
  2. Con MEGAcmd (`mega-export`) genera los enlaces reales y los marca `ok`;
     es reanudable (solo pide lo pendiente/error).
  3. Exporta `data/descargas.json`.

Niveles: `archivo` (cada archivo) · `carpeta` (juegos/letras) · `todos`.

Uso:
    uv run python -m app.indexar_descargas --nivel archivo
    uv run python -m app.indexar_descargas --nivel todos --out ../data/descargas.json
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import megacmd
from .config import settings
from .db import build_engine, create_schema
from .library import current_snapshot
from .models import DownloadLink, Node
from .routers.download import remote_candidates
from .safefs import atomic_write_text

log = logging.getLogger("alucard.descargas")


def registrar_pendientes(session: Session, snap_id: int, nivel: str) -> int:
    """Inserta una fila `pendiente` por cada ruta objetivo que falte."""
    st = select(Node).where(Node.snapshot_id == snap_id)
    if nivel == "archivo":
        st = st.where(Node.kind == "file")
    elif nivel == "carpeta":
        st = st.where(Node.kind == "folder", Node.role.in_(("bucket", "title")))

    existentes = {
        d.path
        for d in session.execute(
            select(DownloadLink).where(DownloadLink.snapshot_id == snap_id)
        ).scalars()
    }
    nuevos = 0
    for n in session.execute(st.order_by(Node.node_order)).scalars():
        if n.path in existentes:
            continue
        session.add(DownloadLink(
            snapshot_id=snap_id, node_id=n.id, path=n.path,
            nivel="archivo" if n.kind == "file" else "carpeta",
            metodo="mega_export", estado="pendiente",
        ))
        nuevos += 1
    session.commit()
    return nuevos


def _exportar_json(session: Session, snap_id: int, out: Path) -> None:
    filas = session.execute(
        select(DownloadLink).where(DownloadLink.snapshot_id == snap_id)
        .order_by(DownloadLink.path)
    ).scalars().all()
    datos = {
        "meta": {
            "snapshot_id": snap_id,
            "total_rutas": len(filas),
            "ok": sum(1 for f in filas if f.estado == "ok"),
            "pendiente": sum(1 for f in filas if f.estado == "pendiente"),
            "error": sum(1 for f in filas if f.estado == "error"),
        },
        "descargas": [
            {"path": f.path, "nivel": f.nivel, "estado": f.estado,
             "link": f.link, "metodo": f.metodo}
            for f in filas
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, json.dumps(datos, ensure_ascii=False, indent=1) + "\n")


def contar(session: Session, snap_id: int) -> dict:
    filas = session.execute(
        select(DownloadLink).where(DownloadLink.snapshot_id == snap_id)
    ).scalars().all()
    return dict(Counter(f.estado for f in filas))


def generar_enlaces(engine, *, nivel: str = "archivo",
                    limite: int | None = None, out: Path | None = None) -> dict:
    """Genera los enlaces pendientes/error con mega-export (reanudable)."""
    stats = {"ok": 0, "error": 0, "pendiente": 0, "total": 0}
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return stats
        rows = session.execute(
            select(DownloadLink)
            .where(DownloadLink.snapshot_id == snap.id,
                   DownloadLink.estado.in_(("pendiente", "error")))
            .order_by(DownloadLink.id)
        ).scalars().all()
        if nivel != "todos":
            rows = [r for r in rows if r.nivel == nivel]
        stats["total"] = len(rows)
        if not rows:
            if out:
                _exportar_json(session, snap.id, out)
            return stats
        if not megacmd.probe().available:
            log.warning("mega-export no disponible: los enlaces quedan pendientes")
            stats["pendiente"] = len(rows)
            if out:
                _exportar_json(session, snap.id, out)
            return stats

        procesadas = 0
        for r in rows:
            if limite is not None and procesadas >= limite:
                break
            link = None
            for remote in remote_candidates(r.path):
                try:
                    link = megacmd.export_link(remote)
                    break
                except megacmd.MegaCmdUnavailable:
                    continue
            if link:
                r.link = link
                r.estado = "ok"
                r.error = None
                r.generado_en = datetime.now(UTC)
                stats["ok"] += 1
            else:
                r.estado = "error"
                r.error = "mega-export no devolvió enlace para ninguna variante de ruta"
                stats["error"] += 1
            procesadas += 1
            if procesadas % 25 == 0:
                session.commit()
                log.info("enlaces %d/%d (ok=%d)", procesadas, stats["total"],
                         stats["ok"])
        session.commit()
        if out:
            _exportar_json(session, snap.id, out)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Indexa rutas y enlaces de descarga MEGA")
    ap.add_argument("--db", default=None)
    ap.add_argument("--nivel", choices=["archivo", "carpeta", "todos"], default="archivo")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--solo-pendientes", action="store_true",
                    help="Registra pendientes sin generar enlaces (sin red)")
    ap.add_argument("--out", default=None, help="JSON de salida (data/descargas.json)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    url = (f"sqlite:///{Path(args.db).expanduser().resolve()}" if args.db
           else settings.resolved_database_url)
    create_schema(url)
    engine = build_engine(url)

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            raise SystemExit("No hay snapshot.")
        nuevos = registrar_pendientes(session, snap.id, args.nivel)
        print(f"Rutas registradas como pendiente (nuevas): {nuevos}")
        if args.solo_pendientes or not megacmd.probe().available:
            print("Estado del índice de descargas:",
                  contar(session, snap.id))
            if args.out:
                _exportar_json(session, snap.id, Path(args.out))
                print(f"JSON → {args.out}")
            if not args.solo_pendientes:
                print("mega-export no disponible: vuelve a ejecutar cuando "
                      "MEGAcmd esté activo para generar los enlaces.")
            return

    stats = generar_enlaces(engine, nivel=args.nivel, limite=args.limite,
                            out=Path(args.out) if args.out else None)
    print("Enlaces generados:", stats)


if __name__ == "__main__":
    main()
