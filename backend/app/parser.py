"""Parser de volcados MEGAcmd (`mega-ls -R -l`) a un árbol normalizado.

Formato soportado (ASCII tree, 4 espacios por nivel, generado por MEGAcmd):

    SECTOR: INSHARE cuenta.base.demo@gmail.com:BCKP1
    [ROOT] //from/...:BCKP1/
    |-- [FOLDER] -- A/
    |   |-- [FOLDER] Game Title/
    |   |   |-- [FOLDER] B-ASE/
    |   |   |   `-- [FILE] name.part1.rar  (104857600 bytes)

Cada entrada ocupa `indent*4` espacios antes de su etiqueta `[FOLDER]`/`[FILE]`,
por lo que `depth = índice_de_la_etiqueta // 4`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import ext_of

FOLDER = "folder"
FILE = "file"

_SIZE_RE = re.compile(r"\s+\((\d+) bytes\)\s*$")
_ROOT_RE = re.compile(r"^\[ROOT\]")

_KIND_KEYS = {
    "cuenta": "account",
    "fecha de volcado": "generated_at",
    "herramienta": "tool",
}


@dataclass
class Node:
    name: str
    kind: str
    depth: int
    size: int = 0
    ext: str | None = None
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = None
    total_size: int = 0
    total_files: int = 0
    total_folders: int = 0

    @property
    def is_folder(self) -> bool:
        return self.kind == FOLDER


@dataclass
class Sector:
    label: str
    roots: list[Node]  # uno por bloque [ROOT] del sector


@dataclass
class ParsedDump:
    account: str | None = None
    tool: str | None = None
    generated_at: str | None = None
    sectors: list[Sector] = field(default_factory=list)
    sha256: str = ""
    warnings: list[str] = field(default_factory=list)
    # Totales globales (archivos/carpetas/bytes)
    file_count: int = 0
    folder_count: int = 0
    total_size: int = 0

    def totals(self) -> dict:
        files = folders = 0
        size = 0
        for sec in self.sectors:
            for root in sec.roots:
                files += root.total_files
                folders += root.total_folders
                size += root.total_size
        return {"files": files, "folders": folders, "size": size}


def _finalize(node: Node) -> tuple[int, int, int]:
    """(size, files, folders) acumulados del subárbol."""
    if not node.is_folder:
        node.total_size = node.size
        node.total_files = 1
        node.total_folders = 0
        return node.total_size, 1, 0
    size = files = folders = 0
    for child in node.children:
        s, f, d = _finalize(child)
        size += s
        files += f
        folders += d
        folders += 1 if child.is_folder else 0
    node.total_size = size
    node.total_files = files
    node.total_folders = folders
    return size, files, folders


def _parse_entry(line: str):
    """Devuelve (kind, depth, name, size) o None si la línea no es un nodo."""
    i_f = line.find("[FOLDER]")
    i_l = line.find("[FILE]")
    if i_f < 0 and i_l < 0:
        return None
    if i_f >= 0 and (i_l < 0 or i_f < i_l):
        kind, idx, rest = FOLDER, i_f, line[i_f + len("[FOLDER]"):]
    else:
        kind, idx, rest = FILE, i_l, line[i_l + len("[FILE]"):]

    depth = idx // 4
    rest = rest.strip()
    if kind == FILE:
        m = _SIZE_RE.search(rest)
        if m:
            size = int(m.group(1))
            name = rest[: m.start()].strip()
        else:
            size, name = 0, rest
    else:
        size = 0
        name = rest.rstrip("/").strip()
    if not name:
        return None
    return kind, depth, name, size


def parse_text(text: str, *, sha256: str = "") -> ParsedDump:
    dump = ParsedDump(sha256=sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest())
    sector: Sector | None = None
    root: Node | None = None
    stack: list[Node] = []
    root_seq = 0

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            continue

        if line.startswith("SECTOR:"):
            label = line.split("SECTOR:", 1)[1].strip()
            sector = Sector(label=label, roots=[])
            dump.sectors.append(sector)
            root = None
            stack = []
            root_seq = 0
            continue

        if sector is None:  # preámbulo (cabecera global del volcado)
            m = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", line)
            if m:
                key = _KIND_KEYS.get(m.group(1).strip().lower())
                if key:
                    setattr(dump, key, m.group(2).strip())
            continue

        if _ROOT_RE.match(line):
            # nuevo bloque de árbol dentro del sector
            if root is not None and root.children:
                root_seq += 1
            name = f"{sector.label} [{root_seq}]" if root_seq else sector.label
            root = Node(name=name, kind=FOLDER, depth=0)
            sector.roots.append(root)
            stack = []
            continue

        entry = _parse_entry(line)
        if entry is None:
            continue
        kind, depth, name, size = entry
        if depth <= 0:
            continue

        while stack and stack[-1].depth >= depth:
            stack.pop()
        parent = stack[-1] if stack else root
        if parent is None:
            dump.warnings.append(f"nodo sin raíz ignorado: {name!r} (línea: {line[:60]})")
            continue

        node = Node(
            name=name,
            kind=kind,
            depth=depth,
            size=size,
            ext=ext_of(name) if kind == FILE else None,
            parent=parent,
        )
        parent.children.append(node)
        if kind == FOLDER:
            stack.append(node)

    for sec in dump.sectors:
        for r in sec.roots:
            _finalize(r)

    t = dump.totals()
    dump.file_count, dump.folder_count, dump.total_size = t["files"], t["folders"], t["size"]
    return dump


def parse_file(path: Path) -> ParsedDump:
    text = path.read_text(encoding="utf-8")
    return parse_text(text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
