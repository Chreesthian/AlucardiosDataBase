"""Ingesta de un volcado MEGAcmd parseado en un `Snapshot` (SQL).

- Persiste el árbol completo (`nodes`) con agregados y roles
  (`root` / `bucket` / `title` / `version`).
- Materializa `titles` (los "juegos") con su resumen de versiones y extensiones.
- Cada ingesta crea un `Snapshot` nuevo (historial inmutable, preparado para
  mostrar diffs en el frontend igual que scrob muestra historial).

Uso CLI:
    uv run python -m app.ingest --dump ../mega_cuenta_contenido_MEGAcmd.txt

Nota de implementación: los nodos se insertan en una sola transacción y, tras
el primer `flush()`, se rellenan `parent_id`/`path` (los IDs ya existen) y se
materializan los `titles`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from itertools import count
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .models import Node, Snapshot, Title
from .normalize import normalize, slugify
from .parser import Node as PNode, ParsedDump, parse_file

_BUCKET_RE = re.compile(r"^-- (?P<letter>.+)$")
_BASE_RE = re.compile(r"^(B-ASE|BASE)\b", re.IGNORECASE)
_UPD_RE = re.compile(r"^(U-PD|UP-D|UPDATE)\b", re.IGNORECASE)
_DLC_RE = re.compile(r"^(\d+\s+)?(D-LC|DLC)\b", re.IGNORECASE)


def is_bucket(name: str) -> bool:
    return bool(_BUCKET_RE.match(name.strip()))


def bucket_letter(name: str) -> str:
    m = _BUCKET_RE.match(name.strip())
    return (m.group("letter").strip().upper() or "#") if m else "#"


def classify_version(name: str) -> str:
    n = name.strip()
    if _BASE_RE.match(n):
        return "base"
    if _UPD_RE.match(n):
        return "update"
    if _DLC_RE.match(n):
        return "dlc"
    return "other"


def role_of(parent_role: str | None, child: PNode) -> str:
    if parent_role is None:
        return "root"
    if parent_role == "root":
        return "bucket" if is_bucket(child.name) else ""
    if parent_role == "bucket":
        return "title" if child.is_folder else ""
    if parent_role == "title":
        return "version" if child.is_folder else ""
    return ""


def next_letter(parent_role: str | None, child: PNode, current: str) -> str:
    if parent_role == "root":
        return bucket_letter(child.name) if is_bucket(child.name) else ""
    return current


def _subtree_exts(node: PNode, acc: Counter) -> None:
    if not node.is_folder:
        if node.ext:
            acc[node.ext] += 1
        return
    for child in node.children:
        _subtree_exts(child, acc)


def ingest(engine, dump: ParsedDump, *, source_kind: str = "dump",
           source_path: str | None = None) -> Snapshot:
    """Persiste un ParsedDump como Snapshot nuevo. Devuelve el Snapshot."""
    snapshot = Snapshot(
        account=dump.account,
        tool=dump.tool,
        generated_at=dump.generated_at,
        source_kind=source_kind,
        source_path=source_path,
        content_sha256=dump.sha256,
        status="ok",
        file_count=dump.file_count,
        folder_count=dump.folder_count,
        total_size=dump.total_size,
    )
    order = count()
    created: list[tuple[PNode, Node]] = []
    title_descs: list[tuple[PNode, Node, str]] = []
    used_slugs: set[str] = set()

    def walk(pnode: PNode, parent_pnode: PNode | None,
             parent_role: str | None, letter: str, path: str) -> None:
        role = role_of(parent_role, pnode)
        row = _insert_node(session, snapshot, pnode, role, path, next(order))
        created.append((pnode, row))
        if role == "title":
            title_descs.append((pnode, row, letter))
        if not pnode.is_folder:
            return
        for child in pnode.children:
            child_path = f"{path}/{child.name}"
            walk(child, pnode, role, next_letter(role, child, letter), child_path)

    with Session(engine) as session:
        session.add(snapshot)
        session.flush()

        for sec in dump.sectors:
            for root in sec.roots:
                walk(root, None, None, "", root.name)

        session.flush()  # asigna ids

        # Pasar 2: fijar parent_id (los ids ya existen tras el flush)
        row_by_pnode = {id(p): r for p, r in created}
        for pnode, row in created:
            if pnode.parent is not None:
                parent_row = row_by_pnode.get(id(pnode.parent))
                if parent_row is not None:
                    row.parent_id = parent_row.id

        # Pasar 3: materializar títulos (juegos)
        for pnode, node_row, letter in title_descs:
            _add_title(session, snapshot, node_row, pnode, letter, used_slugs)

        session.commit()
        session.refresh(snapshot)
    return snapshot


def _insert_node(session: Session, snapshot: Snapshot, node: PNode, role: str,
                 path: str, order: int) -> Node:
    row = Node(
        snapshot_id=snapshot.id,
        path=path,
        name=node.name,
        depth=node.depth,
        kind="folder" if node.is_folder else "file",
        role=role,
        ext=node.ext,
        size=0 if node.is_folder else node.size,
        total_size=node.total_size,
        total_files=node.total_files,
        total_folders=node.total_folders,
        node_order=order,
    )
    session.add(row)
    return row


def _unique_slug(name: str, used: set[str]) -> str:
    base = slugify(name)
    slug = base
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def _add_title(session: Session, snapshot: Snapshot, node_row: Node,
               node: PNode, letter: str, used_slugs: set[str]) -> None:
    version_counts: Counter = Counter()
    for child in node.children:
        if child.is_folder:
            version_counts[classify_version(child.name)] += 1

    exts: Counter = Counter()
    _subtree_exts(node, exts)

    session.add(Title(
        snapshot_id=snapshot.id,
        node_id=node_row.id,
        slug=_unique_slug(node.name, used_slugs),
        name=node.name,
        name_norm=normalize(node.name),
        letter=letter,
        size_bytes=node.total_size,
        file_count=node.total_files,
        folder_count=node.total_folders,
        base_count=version_counts["base"],
        update_count=version_counts["update"],
        dlc_count=version_counts["dlc"],
        other_count=version_counts["other"],
        ext_json=json.dumps(dict(exts), ensure_ascii=False),
    ))


def ingest_file(engine, path: Path, *, source_kind: str = "dump") -> Snapshot:
    dump = parse_file(path)
    return ingest(engine, dump, source_kind=source_kind, source_path=str(path))


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
    ap = argparse.ArgumentParser(description="Ingesta del volcado MEGAcmd a SQLite")
    ap.add_argument("--dump", default=str(settings.resolved_dump),
                    help="Ruta al .txt (dump mega-ls -R -l)")
    ap.add_argument("--db", default=None, help="Ruta SQLite (por defecto data/alucard.db)")
    ap.add_argument("--source", default="dump", choices=["dump", "megacmd"])
    ap.add_argument("--if-empty", action="store_true",
                    help="Solo ingiere si la BD no tiene snapshots (arranque idempotente)")
    args = ap.parse_args()

    path = Path(args.dump).expanduser().resolve()
    engine = _make_engine(args.db)

    if args.if_empty:
        from sqlalchemy import text as sql_text

        with engine.connect() as conn:
            existing = conn.execute(sql_text("SELECT COUNT(*) FROM snapshots")).scalar_one()
        if existing:
            print(f"BD con {existing} snapshot(s) ya presente; --if-empty omite la ingesta.")
            return

    if not path.exists():
        raise SystemExit(f"Volcado no encontrado: {path}")
    print(f"Ingiriendo {path} …")
    snap = ingest_file(engine, path, source_kind=args.source)
    print(
        f"OK snapshot #{snap.id} · {snap.file_count} archivos, "
        f"{snap.folder_count} carpetas, {snap.total_size} bytes · {snap.ingested_at}"
    )


if __name__ == "__main__":
    main()
