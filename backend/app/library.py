"""Capa de servicio: consultas de la biblioteca sobre el snapshot actual.

El snapshot "actual" es el de mayor `id`. Todos los filtros y agregados
trabajan sobre esa fotografía inmutable (historial futuro en F1).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Node, Snapshot, Title
from .plataformas import de_letra

LETTER_ORDER = {c: i for i, c in enumerate("#0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}


def current_snapshot(session: Session) -> Snapshot | None:
    return session.execute(
        select(Snapshot).order_by(Snapshot.id.desc()).limit(1)
    ).scalar_one_or_none()


def _like_escaped(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_buckets(
    session: Session, snapshot_id: int, *, orden_alfabetico: bool = False
) -> list[dict]:
    """Buckets de la colección con su recuento de títulos y su plataforma oficial.

    En Switch el bucket es la LETRA (`#`, `A`…`Z`) y se ordena como el abecedario
    de la UI. En la colección retro el bucket es el SISTEMA (`ARC N-64`,
    `ARC Mame2003`…) y se ordena por el NOMBRE OFICIAL de la plataforma
    (`orden_alfabetico`); `plataforma` es ese nombre, traducido en
    `app.plataformas` (el código del volcado nunca se publica tal cual).
    """
    rows = session.execute(
        select(Title.letter, func.count(Title.id), func.sum(Title.size_bytes))
        .where(Title.snapshot_id == snapshot_id)
        .group_by(Title.letter)
    ).all()
    buckets = [
        {"letter": letra, "titles": n, "size_bytes": s or 0, "plataforma": de_letra(letra)}
        for letra, n, s in rows
    ]
    if orden_alfabetico:
        buckets.sort(key=lambda b: (b["plataforma"].nombre.casefold(), b["letter"].casefold()))
    else:
        buckets.sort(key=lambda b: LETTER_ORDER.get(b["letter"], 99))
    return buckets


def count_covers(session: Session, snapshot_id: int) -> int:
    """Número de títulos con carátula IGDB ya resuelta."""
    return session.execute(
        select(func.count(Title.id)).where(
            Title.snapshot_id == snapshot_id,
            Title.igdb_cover.is_not(None),
        )
    ).scalar_one()


def count_pending_enrich(session: Session, snapshot_id: int) -> int:
    """Títulos sin resolver en IGDB (pendientes de enriquecer)."""
    return session.execute(
        select(func.count(Title.id)).where(
            Title.snapshot_id == snapshot_id,
            (Title.igdb_json.is_(None)) | (Title.igdb_json == ""),
        )
    ).scalar_one()


def list_titles(
    session: Session,
    snapshot_id: int,
    *,
    q: str | None = None,
    letter: str | None = None,
    letters: Sequence[str] | None = None,
    sort: str = "name",
    offset: int = 0,
    limit: int = 60,
    letter_exact: bool = False,
) -> tuple[list[Title], int]:
    """Títulos del snapshot, con filtro por bucket (`letter`) o por plataforma.

    En Switch `letter` es una letra (`A`, `#`…) y se normaliza a mayúsculas; en la
    colección retro es el NOMBRE del sistema (`ARC Mame2003`), así que el router
    retro pasa `letter_exact=True` para respetar el nombre tal cual. Como un
    sistema del volcado puede llamarse de varias formas (`letters`, resueltas con
    `app.plataformas.etiquetas_de`), el filtro por plataforma es un `IN`.
    """
    stmt = select(Title).where(Title.snapshot_id == snapshot_id)
    count_stmt = select(func.count(Title.id)).where(Title.snapshot_id == snapshot_id)

    if letters:
        etiquetas = list(letters)
        stmt = stmt.where(Title.letter.in_(etiquetas))
        count_stmt = count_stmt.where(Title.letter.in_(etiquetas))
    if letter:
        letra = letter if letter_exact else letter.upper()
        stmt = stmt.where(Title.letter == letra)
        count_stmt = count_stmt.where(Title.letter == letra)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        cond = (
            Title.name_norm.like(needle)
            | Title.name.like(f"%{q.strip()}%")
            # IGDB manda: el nombre OFICIAL también encuentra el título (así
            # "After Burner" encuentra la ROM `After Burner.zip`). SQLite hace
            # LIKE sin distinguir mayúsculas en ASCII, suficiente aquí.
            | Title.igdb_name.like(f"%{q.strip()}%")
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = session.execute(count_stmt).scalar_one()

    if sort == "size":
        stmt = stmt.order_by(Title.size_bytes.desc())
    elif sort == "files":
        stmt = stmt.order_by(Title.file_count.desc())
    elif sort == "newest":
        stmt = stmt.order_by(Title.id.desc())
    elif sort == "canonico":
        # Alfabeto del NOMBRE OFICIAL de IGDB; las filas sin match caen a su
        # nombre real para no dejar huecos al final de la lista.
        stmt = stmt.order_by(func.coalesce(Title.igdb_name_norm, Title.name_norm).asc())
    elif sort == "year":
        # Más antiguo primero (catálogo "de época"); sin año, al final.
        stmt = stmt.order_by(func.coalesce(Title.igdb_year, 9999).asc())
    else:  # name: #A…Z y luego alfabético
        stmt = stmt.order_by(Title.name_norm.asc())

    rows = session.execute(stmt.offset(offset).limit(limit)).scalars().all()
    return list(rows), total


def get_title_node(session: Session, snapshot_id: int, node_id: int) -> Node | None:
    return session.execute(
        select(Node).where(
            Node.id == node_id,
            Node.snapshot_id == snapshot_id,
        )
    ).scalar_one_or_none()


def title_detail(session: Session, snapshot_id: int, slug: str) -> tuple[Title | None, dict | None]:
    """Devuelve (Title, estructura) con versiones y archivos del título."""
    title = session.execute(
        select(Title).where(Title.snapshot_id == snapshot_id, Title.slug == slug)
    ).scalar_one_or_none()
    if title is None:
        return None, None

    node = get_title_node(session, snapshot_id, title.node_id)
    if node is None:
        return title, None

    if node.kind == "file":
        # Colección retro: hay juegos que son un ARCHIVO suelto (MAME, Atari…).
        # No hay versiones: el propio archivo es todo el contenido.
        return title, {
            "versions": [],
            "remaining_files": [
                {
                    "name": node.name,
                    "size": node.size,
                    "ext": node.ext,
                    "path": node.name,
                    "full_path": node.path,
                }
            ],
        }

    # Subárbol del título (todas las profundidades), en orden de documento.
    like = _like_escaped(node.path) + "/%"
    rows = (
        session.execute(
            select(Node)
            .where(Node.snapshot_id == snapshot_id, Node.path.like(like, escape="\\"))
            .order_by(Node.node_order)
        )
        .scalars()
        .all()
    )

    by_parent: dict[int | None, list[Node]] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)

    versions: list[dict] = []
    remaining: list[dict] = []

    from .ingest import classify_version  # import local para evitar ciclos

    def walk_files(parent_id: int) -> list[dict]:
        out = []
        for r in by_parent.get(parent_id, []):
            if r.kind == "file":
                out.append(
                    {
                        "name": r.name,
                        "size": r.size,
                        "ext": r.ext,
                        "path": r.path[len(node.path) + 1 :],
                        "full_path": r.path,
                    }
                )
            else:
                out.extend(walk_files(r.id))
        return out

    for child in by_parent.get(node.id, []):
        if child.kind == "folder":
            versions.append(
                {
                    "id": child.id,
                    "name": child.name,
                    "label": classify_version(child.name),
                    "size_bytes": child.total_size,
                    "file_count": child.total_files,
                    "folder_count": child.total_folders,
                    "full_path": child.path,
                    "files": walk_files(child.id),
                }
            )
        else:
            remaining.append(
                {
                    "name": child.name,
                    "size": child.size,
                    "ext": child.ext,
                    "path": child.name,
                    "full_path": child.path,
                }
            )

    structure = {
        "versions": versions,
        "remaining_files": remaining,
    }
    return title, structure


def exts_list(raw: str | None) -> list[str]:
    """Extensiones presentes en `ext_json` (para TitleSummary.formats)."""
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return sorted(k.upper() for k, v in d.items() if isinstance(v, int) and v > 0)
