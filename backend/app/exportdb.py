"""Exporta la biblioteca completa a un JSON estructurado y profesional.

Cada juego incluye: datos locales (tamaño, archivos, versiones B-ASE/U-PD/D-LC,
extensiones, contenido) + ficha IGDB completa (si está enriquecido) + estado del
match. Base canónica: la BD SQLite local.

Uso:
    uv run python -m app.exportdb                      # → data/biblioteca.json
    uv run python -m app.exportdb --out /tmp/b.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import classify_version
from .library import current_snapshot
from .models import Node, Title
from .safefs import atomic_write_text


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _build(title: Title, node: Node | None,
           hijos: dict[int | None, list[Node]]) -> dict:
    ficha = _parse(title.igdb_json)
    if (ficha or {}).get("miss"):
        estado = "miss"
    elif title.igdb_slug and title.igdb_cover:
        estado = "completo"
    elif title.igdb_slug:
        estado = "match_sin_imagen"
    else:
        estado = "pendiente"

    versions: list[dict] = []
    sueltos: list[dict] = []
    if node is not None:

        def archivos_de(parent_id: int, prefijo: str) -> list[dict]:
            out = []
            for n in hijos.get(parent_id, []):
                if n.kind == "file":
                    out.append({
                        "nombre": n.name, "tamano": n.size, "ext": n.ext,
                        "ruta": n.path[len(prefijo) + 1:],
                    })
                else:
                    out.extend(archivos_de(n.id, prefijo))
            return out

        for n in hijos.get(node.id, []):
            if n.kind == "folder":
                versions.append({
                    "nombre": n.name,
                    "tipo": classify_version(n.name),
                    "tamano": n.total_size,
                    "archivos": n.total_files,
                    "carpetas": n.total_folders,
                    "contenido": archivos_de(n.id, node.path),
                })
            else:
                sueltos.append({"nombre": n.name, "tamano": n.size, "ext": n.ext})

    return {
        "slug": title.slug,
        "nombre": title.name,
        "letra": title.letter,
        "tamano_bytes": title.size_bytes,
        "num_archivos": title.file_count,
        "num_carpetas": title.folder_count,
        "versiones_base": title.base_count,
        "versiones_actualizacion": title.update_count,
        "versiones_dlc": title.dlc_count,
        "extensiones": json.loads(title.ext_json or "{}"),
        "estado_igdb": estado,
        "igdb": {"slug": title.igdb_slug, "portada": title.igdb_cover},
        "ficha_igdb": ficha if not (ficha or {}).get("miss") else None,
        "local": {"versiones": versions, "archivos_sueltos": sueltos},
    }


def export(engine, *, out: Path | None = None) -> dict:
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            raise SystemExit("No hay snapshot: ejecuta primero la ingesta.")
        titulos = list(session.execute(
            select(Title).where(Title.snapshot_id == snap.id).order_by(Title.id)
        ).scalars())
        nodos = list(session.execute(
            select(Node).where(Node.snapshot_id == snap.id).order_by(Node.node_order)
        ).scalars())
        hijos: dict[int | None, list[Node]] = defaultdict(list)
        for n in nodos:
            hijos[n.parent_id].append(n)
        nodo_por_id = {n.id: n for n in nodos}

        biblioteca = [
            _build(title=t, node=nodo_por_id.get(t.node_id), hijos=hijos)
            for t in titulos
        ]
        payload = {
            "meta": {
                "fuente": "AlucardiosDataBase · BD local SQLite (snapshot)",
                "snapshot": {
                    "id": snap.id, "cuenta": snap.account,
                    "volcado": snap.generated_at,
                    "ingesta": snap.ingested_at.isoformat(),
                    "archivos": snap.file_count, "carpetas": snap.folder_count,
                    "tamano_bytes": snap.total_size,
                },
                "total_juegos": len(biblioteca),
                "con_caratula": sum(1 for b in biblioteca if b["igdb"]["portada"]),
                "con_ficha_igdb": sum(1 for b in biblioteca if b["ficha_igdb"]),
                "sin_match_igdb": sum(1 for b in biblioteca if b["estado_igdb"] == "miss"),
            },
            "juegos": biblioteca,
        }
    if out is not None:
        atomic_write_text(out, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    return payload["meta"]


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def main() -> None:
    ap = argparse.ArgumentParser(description="Exporta la biblioteca a JSON")
    ap.add_argument("--db", default=None)
    ap.add_argument(
        "--out",
        default=str(Path(settings.resolved_db_path).parent / "biblioteca.json"),
    )
    args = ap.parse_args()
    meta = export(_make_engine(args.db), out=Path(args.out))
    print(f"Exportado a {args.out}")
    print(
        f"  juegos={meta['total_juegos']} · con_caratula={meta['con_caratula']} · "
        f"con_ficha_igdb={meta['con_ficha_igdb']} · sin_match={meta['sin_match_igdb']}"
    )


if __name__ == "__main__":
    main()
