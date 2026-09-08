#!/usr/bin/env python3
"""Construye el volcado final de la cuenta MEGA a partir de listados MEGAcmd (-R -l)."""

import datetime
import re

SECTORS = [
    # (titulo, archivo de listado, nombre raiz para mostrar)
    ("CLOUD_DRIVE", "/home/christian/root_listing.txt", "/"),
    ("INBOX", "/home/christian/inbox_listing.txt", "//in"),
    ("RUBBISH_BIN", "/home/christian/rubbish_listing.txt", "//bin"),
    (
        "INSHARE cuenta.base.demo@gmail.com:BCKP1",
        "/home/christian/bckp1_listing.txt",
        "//from/cuenta.base.demo@gmail.com:BCKP1",
    ),
]

ENTRY_RE = re.compile(
    r"^(?P<flags>[dribx-][a-z-]{3})\s+(?P<vers>\S+)\s+(?P<size>\S+)\s+"
    r"(?P<date>\d{2}\w{3}\d{4} \d{2}:\d{2}:\d{2})\s+(?P<name>.*)$"
)

ACCOUNT = "dueno.demo.mega@gmail.com"


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if n < 1024 or unit == "PiB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0


def parse_listing(path):
    """Devuelve dict {relpath_a_la_raiz_del_sector: (tipo, tamano)}."""
    nodes = {}
    current = None
    base = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if not line or line.startswith("FLAGS"):
                continue
            m = ENTRY_RE.match(line)
            if m:
                if current is None:
                    continue
                name = m.group("name").strip()
                if not name:
                    continue
                full = (current.rstrip("/") + "/" + name) if current not in ("", "/") else name
                if base is not None and full.startswith(base):
                    rel = full[len(base) :].lstrip("/")
                else:
                    rel = full
                t = "folder" if m.group("flags")[0] in "dribx" else "file"
                sz = m.group("size")
                size = int(sz) if sz.isdigit() else 0
                nodes[rel] = (t, size)
            elif line.endswith(":"):
                current = line[:-1]
                if base is None:
                    base = current
    return nodes


def name_of(rel):
    return rel.split("/")[-1] if "/" in rel else rel


def build_lines(nodes, root_label):
    """Devuelve lineas del arbol en ASCII estilo del volcado original."""
    children = {}
    for rel in nodes:
        parts = rel.split("/")
        parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
        children.setdefault(parent, []).append(rel)

    for p in children:
        children[p].sort(key=lambda r: name_of(r).lower())

    counts = {"files": 0, "folders": 0, "bytes": 0}
    for t, s in nodes.values():
        if t == "file":
            counts["files"] += 1
            counts["bytes"] += s
        else:
            counts["folders"] += 1

    lines = [f"[ROOT] {root_label}/"]

    def walk(parent, prefix, is_last):
        kids = children.get(parent, [])
        for i, rel in enumerate(kids):
            last = i == len(kids) - 1
            t, size = nodes[rel]
            nm = name_of(rel)
            branch = "`-- " if last else "|-- "
            label = f"[FOLDER] {nm}/" if t == "folder" else f"[FILE] {nm}"
            if t == "file":
                label += f"  ({size} bytes)"
            lines.append(f"{prefix}{branch}{label}")
            if t == "folder":
                new_pref = prefix + ("    " if last else "|   ")
                walk(rel, new_pref, last)

    walk("", "", True)
    return lines, counts


def main():
    out = "/home/christian/mega_cuenta_contenido_MEGAcmd.txt"
    body = []
    total = {"files": 0, "folders": 0, "bytes": 0}
    for title, listing, root_label in SECTORS:
        nodes = parse_listing(listing)
        lines, counts = build_lines(nodes, root_label)
        body.append("")
        body.append("=" * 72)
        body.append(f"SECTOR: {title}")
        body.append("=" * 72)
        body.append(f"Archivos  : {counts['files']}")
        body.append(f"Carpetas  : {counts['folders']}")
        body.append(f"Tamano    : {counts['bytes']} bytes ({human(counts['bytes'])})")
        body.append("")
        body.extend(lines)
        total["files"] += counts["files"]
        total["folders"] += counts["folders"]
        total["bytes"] += counts["bytes"]

    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    hdr = [
        "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)",
        "=" * 72,
        f"Cuenta            : {ACCOUNT}",
        f"Fecha de volcado  : {now}",
        "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)",
        f"Archivos          : {total['files']}",
        f"Carpetas          : {total['folders']}",
        f"Tamano total      : {total['bytes']} bytes ({human(total['bytes'])})",
        "Formato           : arbol, [ROOT]/[FOLDER]/[FILE]",
        "",
    ]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(hdr + body) + "\n")
    print(f"OK -> {out}  ({len(hdr + body)} lineas)")


if __name__ == "__main__":
    main()
