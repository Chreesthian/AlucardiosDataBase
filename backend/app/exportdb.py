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
from typing import Any, TypeAlias, cast

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import classify_version
from .library import current_snapshot
from .models import Node, Snapshot, Title
from .safefs import atomic_write_text

# Type aliases para mejorar la legibilidad
GameDict: TypeAlias = dict[str, Any]
FileDict: TypeAlias = dict[str, str | int]
VersionDict: TypeAlias = dict[str, str | int | list[FileDict]]
PayloadDict: TypeAlias = dict[str, Any]


def _parse(raw: str | None) -> dict[str, Any] | None:
    """Parsea un string JSON a un diccionario."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _archivos_de(
    hijos_por_id: dict[int, list[Node]], parent_id: int, prefijo: str
) -> list[FileDict]:
    """Recursivamente obtiene todos los archivos de una carpeta."""
    archivos: list[FileDict] = []

    def _recursivo(node_id: int, current_prefijo: str) -> None:
        for n in hijos_por_id.get(node_id, []):
            if n.kind == "file":
                # Asegurar que los campos no sean None
                nombre: str = n.name or ""
                tamanio: int = n.size or 0
                ext: str = n.ext or ""
                ruta: str = n.path[len(current_prefijo) + 1 :] if n.path else ""

                archivos.append(
                    {
                        "nombre": nombre,
                        "tamano": tamanio,
                        "ext": ext,
                        "ruta": ruta,
                    }
                )
            else:
                _recursivo(n.id, current_prefijo)

    _recursivo(parent_id, prefijo)
    return archivos


def _build(title: Title, node: Node | None, hijos: dict[int | None, list[Node]]) -> GameDict:
    """Construye el diccionario de un juego para la exportación."""
    ficha: dict[str, Any] | None = _parse(title.igdb_json)

    # Determinar estado del match IGDB
    if (ficha or {}).get("miss"):
        estado = "miss"
    elif title.igdb_slug and title.igdb_cover:
        estado = "completo"
    elif title.igdb_slug:
        estado = "match_sin_imagen"
    else:
        estado = "pendiente"

    versions: list[VersionDict] = []
    sueltos: list[FileDict] = []

    if node is not None:
        # Crear diccionario de nodos por ID para acceso rápido
        hijos_por_id: dict[int, list[Node]] = defaultdict(list)
        for n in hijos.get(node.id, []):
            if n.kind == "folder":
                hijos_por_id[n.id].append(n)
            elif n.kind == "file":
                # Asegurar que los campos no sean None
                nombre: str = n.name or ""
                tamanio: int = n.size or 0
                ext: str = n.ext or ""

                sueltos.append(
                    {
                        "nombre": nombre,
                        "tamano": tamanio,
                        "ext": ext,
                    }
                )

        # Procesar versiones (carpetas)
        for n in hijos.get(node.id, []):
            if n.kind == "folder":
                # Asegurar que los campos no sean None
                nombre_ver: str = n.name or ""
                tamano_ver: int = n.total_size or 0
                archivos_ver: int = n.total_files or 0
                carpetas_ver: int = n.total_folders or 0

                versions.append(
                    {
                        "nombre": nombre_ver,
                        "tipo": classify_version(nombre_ver),
                        "tamano": tamano_ver,
                        "archivos": archivos_ver,
                        "carpetas": carpetas_ver,
                        "contenido": _archivos_de(hijos_por_id, n.id, node.path or ""),
                    }
                )

    # Construir el diccionario final del juego
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


def export(engine: Engine, *, out: Path | None = None) -> dict[str, Any]:
    """Exporta la biblioteca completa a un diccionario y opcionalmente a un archivo JSON."""
    with Session(engine) as session:
        snap: Snapshot | None = current_snapshot(session)
        if snap is None:
            raise SystemExit("No hay snapshot: ejecuta primero la ingesta.")

        # Obtener todos los títulos del snapshot actual
        titulos: list[Title] = list(
            session.execute(
                select(Title).where(Title.snapshot_id == snap.id).order_by(Title.id)
            ).scalars()
        )

        # Obtener todos los nodos del snapshot
        nodos: list[Node] = list(
            session.execute(
                select(Node).where(Node.snapshot_id == snap.id).order_by(Node.node_order)
            ).scalars()
        )

        # Agrupar nodos por parent_id
        hijos: dict[int | None, list[Node]] = defaultdict(list)
        for n in nodos:
            hijos[n.parent_id].append(n)

        # Diccionario para acceso rápido por ID
        nodo_por_id: dict[int, Node] = {n.id: n for n in nodos}

        # Construir lista de juegos
        biblioteca: list[GameDict] = []
        for t in titulos:
            node: Node | None = nodo_por_id.get(t.node_id) if t.node_id is not None else None
            biblioteca.append(_build(title=t, node=node, hijos=hijos))

        # Construir payload completo
        payload: PayloadDict = {
            "meta": {
                "fuente": "AlucardiosDataBase · BD local SQLite (snapshot)",
                "snapshot": {
                    "id": snap.id,
                    "cuenta": snap.account,
                    "volcado": snap.generated_at,
                    "ingesta": snap.ingested_at.isoformat(),
                    "archivos": snap.file_count,
                    "carpetas": snap.folder_count,
                    "tamano_bytes": snap.total_size,
                },
                "total_juegos": len(biblioteca),
                "con_caratula": sum(1 for b in biblioteca if b.get("igdb", {}).get("portada")),
                "con_ficha_igdb": sum(1 for b in biblioteca if b.get("ficha_igdb")),
                "sin_match_igdb": sum(1 for b in biblioteca if b.get("estado_igdb") == "miss"),
            },
            "juegos": biblioteca,
        }

    # Escribir archivo si se especifica
    if out is not None:
        atomic_write_text(out, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")

    return cast(dict[str, Any], payload["meta"])


def _make_engine(db_arg: str | None = None) -> Engine:
    """Crea un motor de base de datos a partir de la URL o ruta proporcionada."""
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def main() -> None:
    """Punto de entrada principal del script."""
    ap = argparse.ArgumentParser(description="Exporta la biblioteca a JSON")
    ap.add_argument("--db", default=None, help="Ruta a la base de datos SQLite")
    ap.add_argument(
        "--out",
        default=str(Path(settings.resolved_db_path).parent / "biblioteca.json"),
        help="Ruta de salida para el archivo JSON",
    )
    args = ap.parse_args()

    # Realizar exportación
    meta: dict[str, Any] = export(_make_engine(args.db), out=Path(args.out))

    # Mostrar resultados
    print(f"Exportado a {args.out}")
    print(
        f"  juegos={meta['total_juegos']} · con_caratula={meta['con_caratula']} · "
        f"con_ficha_igdb={meta['con_ficha_igdb']} · sin_match={meta['sin_match_igdb']}"
    )


if __name__ == "__main__":
    main()
