"""Sincronización incremental del árbol MEGA contra la BD local.

Objetivo: escaneos periódicos que detectan archivos/carpetas **añadidos y
borrados** sin "rehacer" la base de datos.

Cómo funciona (en el snapshot vigente, en sitio):
  1. Parsa el volcado nuevo y calcula el diff contra las rutas ya guardadas.
  2. SUSTRACCIÓN: borra únicamente los nodos que ya no existen (con sus
     títulos, por cascada) → nada más se toca.
  3. ADICIÓN: inserta únicamente los nodos nuevos (con su jerarquía).
  4. Cambios de tamaño en archivos → se actualiza el tamaño.
  5. Recalcula (barato, O(n) en memoria) agregados de carpetas, roles y los
     resúmenes de títulos derivados. Los títulos que PERSISTEN conservan su
     enriquecimiento IGDB (`igdb_slug/igdb_cover/igdb_json`).
  6. Registra el escaneo en `sync_logs` (añadidos/borrados/cambiados).

Si no hay snapshot previo, hace la ingesta inicial completa (bootstrap).

Uso:
    uv run python -m app.sync --dump ../mega_cuenta_contenido_MEGAcmd.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import bucket_letter, classify_version, ingest, is_bucket
from .models import Node, Snapshot, SyncLog, Title
from .normalize import normalize, slugify
from .parser import FOLDER, Node as PNode, ParsedDump, parse_file, parse_text

log = logging.getLogger("alucard.sync")


def _collect(parsed: ParsedDump) -> dict[str, PNode]:
    """Rutas deseadas tras el nuevo escaneo (path → PNode del parser)."""
    nuevo: dict[str, PNode] = {}

    def walk(n: PNode, path: str) -> None:
        nuevo[path] = n
        for c in n.children:
            walk(c, f"{path}/{c.name}")

    for sec in parsed.sectors:
        for root in sec.roots:
            walk(root, root.name)
    return nuevo


def refresh(engine, parsed: ParsedDump, *, kind: str = "dump",
            source_path: str | None = None,
            allow_empty: bool = False) -> dict:
    """Actualiza la BD por diferencias. Devuelve resumen del escaneo.

    Blindaje: si la BD tiene contenido y el nuevo volcado NO trae archivos
    (fichero vacío/truncado/borrado por error), aborta en vez de vaciar la
    biblioteca. `allow_empty=True` fuerza el vaciado consciente (CLI --allow-vacio).
    """
    stats = {"kind": kind, "source_path": source_path, "bootstrap": False,
             "added_files": 0, "removed_files": 0, "changed_files": 0,
             "added_folders": 0, "removed_folders": 0,
             "total_files": parsed.file_count, "total_folders": parsed.folder_count}

    with Session(engine) as session:
        snap = session.execute(
            select(Snapshot).order_by(Snapshot.id.desc()).limit(1)
        ).scalar_one_or_none()

        if snap is None:
            # Primera vez: ingesta completa (bootstrap), no hay nada que destruir.
            ingest(engine, parsed, source_kind=kind, source_path=source_path)
            stats["bootstrap"] = True
            stats["added_files"] = parsed.file_count
            stats["added_folders"] = parsed.folder_count
            return stats

        sid = snap.id
        filas = list(session.execute(
            select(Node).where(Node.snapshot_id == sid)
        ).scalars())
        exist = {r.path: r for r in filas}
        nuevo = _collect(parsed)

        # Blindaje: un volcado vacío/truncado NUNCA debe vaciar la biblioteca.
        actuales_archivos = sum(1 for r in filas if r.kind == "file")
        if actuales_archivos and parsed.file_count == 0 and not allow_empty:
            raise RuntimeError(
                "Volcado sin archivos (file_count=0) pero la BD tiene "
                f"{actuales_archivos} archivos → se ABORTA para no borrar nada. "
                "Si el vaciado es intencionado, vuelve a ejecutar con --allow-vacio."
            )

        # 1) SUSTRACCIÓN: rutas que ya no existen en el escaneo.
        removidos = set(exist) - set(nuevo)
        for p in removidos:
            session.delete(exist[p])
            if exist[p].kind == "file":
                stats["removed_files"] += 1
            else:
                stats["removed_folders"] += 1

        # 2) ADICIÓN: rutas nuevas (padres antes que hijos).
        añadidos = sorted(
            (set(nuevo) - set(exist)),
            key=lambda x: (len(x.split("/")), x),
        )
        max_order = max((r.node_order for r in filas), default=0)
        order = max_order + 1
        by_path: dict[str, Node] = {p: r for p, r in exist.items() if p not in removidos}
        insertados: list[tuple[str, Node]] = []
        for p in añadidos:
            n = nuevo[p]
            row = Node(
                snapshot_id=sid, path=p, name=n.name, depth=n.depth,
                kind="folder" if n.is_folder else "file", role="",
                ext=n.ext, size=0 if n.is_folder else n.size, node_order=order,
            )
            session.add(row)
            order += 1
            insertados.append((p, row))
            by_path[p] = row
            if n.is_folder:
                stats["added_folders"] += 1
            else:
                stats["added_files"] += 1
        session.flush()

        for p, row in insertados:
            parent = p.rsplit("/", 1)[0] if "/" in p else None
            row.parent_id = by_path[parent].id if parent else None

        # 3) Cambios: mismo archivo con otro tamaño.
        for p in set(exist) & set(nuevo):
            e, n = exist[p], nuevo[p]
            if not n.is_folder and e.size != n.size:
                e.size = n.size
                stats["changed_files"] += 1

        # 4) Estado derivado (agregados/roles/títulos) sobre el árbol final.
        _recalcular(session, sid)

        snap.file_count = parsed.file_count
        snap.folder_count = parsed.folder_count
        snap.total_size = parsed.total_size
        snap.content_sha256 = parsed.sha256
        if source_path:
            snap.source_path = source_path

        session.add(SyncLog(
            snapshot_id=sid, kind=kind, source_path=source_path,
            added_files=stats["added_files"], removed_files=stats["removed_files"],
            changed_files=stats["changed_files"],
            added_folders=stats["added_folders"], removed_folders=stats["removed_folders"],
            total_files=parsed.file_count, total_folders=parsed.folder_count,
        ))
        session.commit()
    return stats


def _rol_hijo(parent_role: str | None, nombre: str, kind: str) -> str:
    if parent_role is None:
        return "root"
    if parent_role == "root":
        return "bucket" if is_bucket(nombre) else ""
    if parent_role == "bucket":
        return "title" if kind == "folder" else ""
    if parent_role == "title":
        return "version" if kind == "folder" else ""
    return ""


def _recalcular(session: Session, sid: int) -> None:
    """Reasigna roles y agregados y refresca títulos derivados (en sitio).

    Solo sobreescribe lo derivado: los títulos que persisten conservan su
    `igdb_slug/igdb_cover/igdb_json`; los nuevos se crean; los eliminados se
    borran (ya cascadearon al quitar su nodo).
    """
    nodos = list(session.execute(
        select(Node).where(Node.snapshot_id == sid)
    ).scalars())
    hijos: dict[int, list[Node]] = defaultdict(list)
    for r in nodos:
        if r.parent_id is not None:
            hijos[r.parent_id].append(r)
    titulos = {
        t.node_id: t
        for t in session.execute(
            select(Title).where(Title.snapshot_id == sid)
        ).scalars()
    }
    usados = {t.slug for t in titulos.values()}
    titulos_vivos: set[int] = set()

    def _nuevo_slug(nombre: str) -> str:
        base = slugify(nombre)
        slug = base
        n = 2
        while slug in usados:
            slug = f"{base}-{n}"
            n += 1
        usados.add(slug)
        return slug

    def walk(row: Node, parent_role: str | None, letra_bucket: str):
        role = _rol_hijo(parent_role, row.name, row.kind)
        row.role = role if row.kind == "folder" else ""
        if row.kind != "folder":
            return row.size, 1, 0, Counter({row.ext: 1} if row.ext else {})

        size = files = folders = 0
        ext_sum = Counter()
        versiones: Counter = Counter()
        for child in hijos.get(row.id, []):
            if child.kind == "file":
                size += child.size
                files += 1
                if child.ext:
                    ext_sum[child.ext] += 1
                child.total_size, child.total_files, child.total_folders = child.size, 1, 0
                continue
            letra_hijo = (
                bucket_letter(row.name)
                if role == "bucket"
                else (bucket_letter(child.name) if (role == "root" and is_bucket(child.name)) else "")
            )
            s, f, d, ex = walk(child, role, letra_hijo)
            size += s
            files += f
            folders += d + 1
            ext_sum.update(ex)
            if role == "title":
                versiones[classify_version(child.name)] += 1

        row.total_size, row.total_files, row.total_folders = size, files, folders

        if role == "title":
            titulos_vivos.add(row.id)
            ext_json = json.dumps(dict(ext_sum), ensure_ascii=False)
            t = titulos.get(row.id)
            if t is None:
                session.add(Title(
                    snapshot_id=sid, node_id=row.id, slug=_nuevo_slug(row.name),
                    name=row.name, name_norm=normalize(row.name), letter=letra_bucket,
                    size_bytes=size, file_count=files, folder_count=folders,
                    base_count=versiones["base"], update_count=versiones["update"],
                    dlc_count=versiones["dlc"], other_count=versiones["other"],
                    ext_json=ext_json,
                ))
            else:
                # Conserva igdb_*; refresca solo lo derivado del árbol.
                t.size_bytes, t.file_count, t.folder_count = size, files, folders
                t.base_count, t.update_count = versiones["base"], versiones["update"]
                t.dlc_count, t.other_count = versiones["dlc"], versiones["other"]
                t.ext_json = ext_json
        return size, files, folders, ext_sum

    for r in nodos:
        if r.parent_id is None:
            walk(r, None, "")

    # Títulos huérfanos (su nodo dejó de ser título o fue borrado).
    for node_id, t in titulos.items():
        if node_id not in titulos_vivos:
            session.delete(t)


def refresh_file(engine, path: Path, *, kind: str = "dump",
                 allow_empty: bool = False) -> dict:
    """Lee el volcado UNA sola vez (hash y parse del MISMO texto) y sincroniza."""
    texto = path.read_text(encoding="utf-8")
    parsed = parse_text(texto, sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest())
    return refresh(engine, parsed, kind=kind, source_path=str(path),
                   allow_empty=allow_empty)


def refresh_text(engine, texto: str, *, kind: str = "dump",
                 allow_empty: bool = False) -> dict:
    return refresh(engine, parse_text(texto), kind=kind, source_path=None,
                   allow_empty=allow_empty)


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def _huella(path: Path) -> str:
    """SHA-256 del volcado (detección de cambios para el modo --watch)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _una_pasada(engine, path: Path, exportar: bool,
                allow_vacio: bool = False) -> dict:
    stats = refresh_file(engine, path, kind="dump", allow_empty=allow_vacio)
    print(
        f"[{stats['kind']}] bootstrap={stats['bootstrap']} | "
        f"+{stats['added_files']} archivos +{stats['added_folders']} carpetas | "
        f"-{stats['removed_files']} archivos -{stats['removed_folders']} carpetas | "
        f"~{stats['changed_files']} cambiados"
    )
    print(
        f"Estado final: {stats['total_files']} archivos, "
        f"{stats['total_folders']} carpetas."
    )
    if exportar:
        from .exportdb import export

        destino = Path(settings.resolved_db_path).parent / "biblioteca.json"
        meta = export(engine, out=destino)
        print(f"Exportado a {destino} (juegos={meta['total_juegos']})")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Escaneo incremental: actualiza la BD por diferencias "
                    "(añadidos/borrados) sin reconstruir."
    )
    ap.add_argument("--dump", default=str(settings.resolved_dump),
                    help="Ruta al volcado .txt (o volcado MEGAcmd actual)")
    ap.add_argument("--db", default=None, help="Ruta SQLite")
    ap.add_argument("--export", action="store_true",
                    help="Regenera data/biblioteca.json tras sincronizar")
    ap.add_argument("--watch", action="store_true",
                    help="Modo daemon: vigila el volcado y sincroniza SOLO cuando cambia")
    ap.add_argument("--interval", type=int, default=300,
                    help="Segundos entre comprobaciones en --watch (def. 300)")
    ap.add_argument("--allow-vacio", action="store_true",
                    help="Permite aplicar un volcado con 0 archivos (vaciado consciente)")
    args = ap.parse_args()

    path = Path(args.dump).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Volcado no encontrado: {path}")

    engine = _make_engine(args.db)

    if not args.watch:
        _una_pasada(engine, path, args.export, args.allow_vacio)
        return

    # ── Modo daemon autónomo: espera a que el volcado cambie en disco. ──
    print(f"[sync-watch] vigilando {path} cada {args.interval}s "
          "(primer escaneo inmediato). Detén con señal/Ctrl+C.")
    ultima_huella: str | None = None
    while True:
        try:
            if not path.exists():
                log.warning("volcado ausente: %s; reintento en %ss",
                            path, args.interval)
            else:
                huella = _huella(path)
                if huella != ultima_huella:
                    ultima_huella = huella
                    _una_pasada(engine, path, args.export, args.allow_vacio)
                else:
                    log.info("volcado sin cambios; próxima comprobación en %ss",
                             args.interval)
        except KeyboardInterrupt:
            print("[sync-watch] detenido.")
            return
        except Exception:
            log.exception("error en pasada de sync; reintento en %ss",
                          args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
