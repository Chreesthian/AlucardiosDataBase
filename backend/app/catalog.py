"""Catálogo interno completo del contenido MEGA indexado.

Indexa y clasifica TODO el árbol (no solo los juegos): sectores, carpetas de
letra, títulos, versiones (Base/Actualización/DLC/…), contenido no clasificado
y cada archivo con su familia de formato. Se sirve internamente (API + JSON).

Utilidades:
    - catalogar(engine)          → resumen clasificado (raíces, buckets, formatos)
    - info_carpeta(engine, path) → contenido e info completa de una carpeta

CLI:
    uv run python -m app.catalog                  # imprime resumen
    uv run python -m app.catalog --out data/catalogo.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import bucket_letter, classify_version
from .library import current_snapshot
from .models import Node
from .safefs import atomic_write_text

# ── Clasificación de formatos (familias) ──────────────────────────────────
_FORMATO_FAMILIA = {
    "rar": "Archivo comprimido RAR",
    "zip": "Archivo comprimido ZIP",
    "7z": "Archivo comprimido 7-Zip",
    "nsp": "Paquete Nintendo Switch (NSP)",
    "nsz": "Paquete Nintendo Switch NSZ",
    "xci": "Imagen cartucho Switch (XCI)",
    "xcz": "Imagen cartucho Switch XCZ",
    "txt": "Texto / nota",
    "nfo": "Ficha NFO",
    "pdf": "Documento PDF",
    "jpg": "Imagen JPG",
    "jpeg": "Imagen JPEG",
    "png": "Imagen PNG",
    "iso": "Imagen de disco ISO",
    "cue": "CUE (CD)",
    "chd": "CHD (disco comprimido)",
    "md": "ROM Mega Drive",
    "nes": "ROM NES",
    "snes": "ROM SNES",
    "gba": "ROM Game Boy Advance",
    "gbc": "ROM Game Boy Color",
    "nds": "ROM Nintendo DS",
    "3ds": "ROM Nintendo 3DS",
    "cia": "Instalable 3DS (CIA)",
}

ROLES_LABEL = {
    "root": "Raíz de sector",
    "bucket": "Carpeta de letra",
    "title": "Juego",
    "version": "Variante",
}
_VERSION_LABEL = {"base": "Base", "update": "Actualización", "dlc": "DLC", "other": "Variante"}


def familia_formato(ext: str | None) -> str:
    if not ext:
        return "Sin extensión"
    return _FORMATO_FAMILIA.get(ext.lower(), f"Formato {ext.upper()}")


def etiqueta_nodo(row) -> str:
    """Etiqueta semántica de un nodo (carpeta o archivo)."""
    if row.kind != "folder":
        return "Archivo"
    if row.role == "version":
        return _VERSION_LABEL.get(classify_version(row.name), "Variante")
    return ROLES_LABEL.get(row.role, "Carpeta")


def _cargar(session: Session, snap_id: int) -> tuple[list[Node], dict[int, list[Node]]]:
    nodos = list(session.execute(
        select(Node).where(Node.snapshot_id == snap_id).order_by(Node.node_order)
    ).scalars())
    hijos: dict[int, list[Node]] = defaultdict(list)
    for n in nodos:
        if n.parent_id is not None:
            hijos[n.parent_id].append(n)
    return nodos, hijos


def catalogar(engine) -> dict:
    """Resumen clasificado de TODA la biblioteca indexada."""
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return {"error": "sin snapshot"}
        nodos, hijos = _cargar(session, snap.id)

        por_formato: Counter = Counter()
        bytes_formato: Counter = Counter()
        familias: Counter = Counter()
        rol_carpetas: Counter = Counter()
        total_archivos = total_bytes = total_carpetas = titulos = 0

        for n in nodos:
            if n.kind == "file":
                total_archivos += 1
                total_bytes += n.size
                ext = n.ext or "(sin ext)"
                por_formato[ext] += 1
                bytes_formato[ext] += n.size
                familias[familia_formato(n.ext)] += 1
            else:
                total_carpetas += 1
                if n.role:
                    rol_carpetas[n.role] += 1
                    if n.role == "title":
                        titulos += 1

        raices: list[dict] = []
        for root in [n for n in nodos if n.parent_id is None]:
            buckets = []
            otros = 0
            for ch in hijos.get(root.id, []):
                if ch.role == "bucket":
                    bucket_titulos = sum(
                        1 for x in hijos.get(ch.id, []) if x.role == "title"
                    )
                    buckets.append({
                        "nombre": ch.name, "letra": bucket_letter(ch.name),
                        "titulos": bucket_titulos, "carpetas": ch.total_folders,
                        "archivos": ch.total_files, "bytes": ch.total_size,
                    })
                else:
                    otros += 1
            buckets.sort(key=lambda b: (b["letra"] == "#", b["letra"]))
            raices.append({
                "sector": root.name, "carpetas": root.total_folders,
                "archivos": root.total_files, "bytes": root.total_size,
                "buckets": buckets, "otros_nodos": otros,
            })

        return {
            "generado": snap.ingested_at.isoformat(),
            "snapshot": {"id": snap.id, "cuenta": snap.account},
            "resumen": {
                "archivos": total_archivos, "carpetas": total_carpetas,
                "bytes": total_bytes, "titulos_juegos": titulos,
                "versiones": rol_carpetas.get("version", 0),
                "carpetas_de_letra": rol_carpetas.get("bucket", 0),
                "por_formato": {
                    ext: {"archivos": c, "bytes": bytes_formato[ext]}
                    for ext, c in por_formato.most_common()
                },
                "por_familia": dict(familias.most_common()),
            },
            "raices": raices,
        }


def info_carpeta(engine, path: str) -> dict | None:
    """Información completa de una carpeta y de su contenido directo."""
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return None
        carpeta = session.execute(
            select(Node).where(Node.snapshot_id == snap.id, Node.path == path)
        ).scalars().first()
        if carpeta is None or carpeta.kind != "folder":
            return None
        hijos = session.execute(
            select(Node).where(Node.snapshot_id == snap.id, Node.parent_id == carpeta.id)
            .order_by(Node.node_order)
        ).scalars().all()
        hijos_info = [{
            "nombre": ch.name, "path": ch.path,
            "tipo": "carpeta" if ch.kind == "folder" else "archivo",
            "etiqueta": etiqueta_nodo(ch), "ext": ch.ext,
            "tamano": ch.size,
            "sub_archivos": ch.total_files, "sub_carpetas": ch.total_folders,
            "sub_bytes": ch.total_size,
        } for ch in hijos]
        return {
            "path": carpeta.path, "nombre": carpeta.name,
            "etiqueta": etiqueta_nodo(carpeta),
            "archivos_directos": carpeta.total_files,
            "carpetas_totales": carpeta.total_folders, "bytes": carpeta.total_size,
            "contenido": hijos_info,
        }


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def _resumir_texto(cat: dict) -> str:
    r = cat["resumen"]
    lineas = [
        f"SNAPSHOT #{cat['snapshot']['id']} · {cat['snapshot']['cuenta']}",
        f"  Archivos: {r['archivos']:,} · Carpetas: {r['carpetas']:,} · "
        f"Bytes: {r['bytes']:,}",
        f"  Juegos (títulos): {r['titulos_juegos']:,} · Versiones: "
        f"{r['versiones']:,} · Carpetas de letra: {r['carpetas_de_letra']}",
    ]
    if r["por_formato"]:
        fmt = ", ".join(
            f"{ext}:{d['archivos']}" for ext, d in list(r["por_formato"].items())[:6]
        )
        lineas.append(f"  Formatos (ext:nº): {fmt}")
    return "\n".join(lineas)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Catálogo interno clasificado del contenido MEGA")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None,
                    help="Ruta JSON de salida (p. ej. data/catalogo.json)")
    ap.add_argument("--carpeta", default=None,
                    help="Imprime la información completa de una carpeta (path)")
    args = ap.parse_args()

    engine = _make_engine(args.db)
    if args.carpeta:
        info = info_carpeta(engine, args.carpeta)
        print(json.dumps(info or {"error": "carpeta no encontrada"},
                         ensure_ascii=False, indent=2))
        return

    cat = catalogar(engine)
    print(_resumir_texto(cat))
    for raiz in cat["raices"]:
        print(f"\n· {raiz['sector']} — {raiz['archivos']:,} archivos, "
              f"{raiz['carpetas']:,} carpetas, {raiz['bytes']:,} bytes")
        for b in raiz["buckets"]:
            print(f"    {b['letra']:>2} · {b['titulos']:>5} juegos · "
                  f"{b['archivos']:>6} archivos · {b['bytes']:>15,} bytes")

    if args.out:
        out = Path(args.out)
        atomic_write_text(out, json.dumps(cat, ensure_ascii=False, indent=1) + "\n")
        print(f"\nCatálogo JSON → {out}")


if __name__ == "__main__":
    main()
