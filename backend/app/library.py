"""Capa de servicio: consultas de la biblioteca sobre el snapshot actual.

El snapshot "actual" es el de mayor `id`. Todos los filtros y agregados
trabajan sobre esa fotografía inmutable (historial futuro en F1).
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Node, Snapshot, Title

LETTER_ORDER = {c: i for i, c in enumerate("#0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}


def current_snapshot(session: Session) -> Snapshot | None:
    return session.execute(
        select(Snapshot).order_by(Snapshot.id.desc()).limit(1)
    ).scalar_one_or_none()


def _like_escaped(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_buckets(session: Session, snapshot_id: int) -> list[dict]:
    rows = session.execute(
        select(Title.letter, func.count(Title.id), func.sum(Title.size_bytes))
        .where(Title.snapshot_id == snapshot_id)
        .group_by(Title.letter)
    ).all()
    buckets = [{"letter": l, "titles": n, "size_bytes": s or 0} for l, n, s in rows]
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
    sort: str = "name",
    offset: int = 0,
    limit: int = 60,
) -> tuple[list[Title], int]:
    stmt = select(Title).where(Title.snapshot_id == snapshot_id)
    count_stmt = select(func.count(Title.id)).where(Title.snapshot_id == snapshot_id)

    if letter:
        letter = letter.upper()
        stmt = stmt.where(Title.letter == letter)
        count_stmt = count_stmt.where(Title.letter == letter)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        cond = Title.name_norm.like(needle) | Title.name.like(f"%{q.strip()}%")
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = session.execute(count_stmt).scalar_one()

    if sort == "size":
        stmt = stmt.order_by(Title.size_bytes.desc())
    elif sort == "files":
        stmt = stmt.order_by(Title.file_count.desc())
    elif sort == "newest":
        stmt = stmt.order_by(Title.id.desc())
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


def title_detail(
    session: Session, snapshot_id: int, slug: str
) -> tuple[Title | None, dict | None]:
    """Devuelve (Title, estructura) con versiones y archivos del título."""
    title = session.execute(
        select(Title).where(Title.snapshot_id == snapshot_id, Title.slug == slug)
    ).scalar_one_or_none()
    if title is None:
        return None, None

    node = get_title_node(session, snapshot_id, title.node_id)
    if node is None:
        return title, None

    # Subárbol del título (todas las profundidades), en orden de documento.
    like = _like_escaped(node.path) + "/%"
    rows = session.execute(
        select(Node)
        .where(Node.snapshot_id == snapshot_id, Node.path.like(like, escape="\\"))
        .order_by(Node.node_order)
    ).scalars().all()

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
                out.append({"name": r.name, "size": r.size, "ext": r.ext,
                            "path": r.path[len(node.path) + 1:],
                            "full_path": r.path})
            else:
                out.extend(walk_files(r.id))
        return out

    for child in by_parent.get(node.id, []):
        if child.kind == "folder":
            versions.append({
                "id": child.id,
                "name": child.name,
                "label": classify_version(child.name),
                "size_bytes": child.total_size,
                "file_count": child.total_files,
                "folder_count": child.total_folders,
                "full_path": child.path,
                "files": walk_files(child.id),
            })
        else:
            remaining.append({"name": child.name, "size": child.size,
                              "ext": child.ext, "path": child.name,
                              "full_path": child.path})

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
