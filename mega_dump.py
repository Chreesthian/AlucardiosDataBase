#!/usr/bin/env python3
"""Vuelca el árbol completo de una cuenta MEGA a un archivo de texto."""

import datetime
import os

from mega import Mega

EMAIL = os.environ["MEGA_EMAIL"]
PASSWORD = os.environ["MEGA_PASSWORD"]
OUT = os.environ.get("MEGA_OUT", os.path.expanduser("~/mega_cuenta_contenido.txt"))

TYPE_NAME = {0: "FILE", 1: "FOLDER", 2: "ROOT", 3: "INBOX", 4: "TRASH"}


def main():
    mega = Mega()
    m = mega.login(EMAIL, PASSWORD)

    files = m.get_files()
    nodes = {}
    for handle, datos in files.items():
        meta = dict(datos)
        meta["h"] = handle
        nodes[handle] = meta

    # Ubicar raíces especiales (Cloud Drive, Inbox, Rubbish Bin) y las suyas.
    cloud = None
    inbox = None
    trash = None
    for h, meta in nodes.items():
        t = meta.get("t")
        if t == 2 and cloud is None:
            cloud = h
        elif t == 3 and inbox is None:
            inbox = h
        elif t == 4 and trash is None:
            trash = h

    root_names = {}
    if cloud:
        root_names[cloud] = "CLOUD_DRIVE"
    if inbox:
        root_names[inbox] = "INBOX"
    if trash:
        root_names[trash] = "RUBBISH_BIN"

    # Mapa hijos -> lista de handles.
    children = {}
    orphan_roots = []
    for h, meta in nodes.items():
        p = meta.get("p")
        if p in nodes and meta.get("t") in (0, 1):
            children.setdefault(p, []).append(h)
        elif meta.get("t") in (0, 1):
            orphan_roots.append(h)

    # Nodo contenido bajo los 'roots' conocidos y nodos sueltos (p.ej. compartidos).
    top_roots = list(root_names.keys()) + orphan_roots

    def name_of(h):
        n = nodes[h].get("a")
        return (n or {}).get("n", "<sin-nombre>") if isinstance(n, dict) else "<sin-nombre>"

    def sort_children(lst):
        return sorted(lst, key=lambda h: name_of(h).lower())

    lines = []
    counts = {"files": 0, "folders": 0, "orphans": 0}

    for root in top_roots:
        if root in root_names:
            section = root_names[root]
            lines.append("")
            lines.append("=" * 72)
            lines.append(f"SECTOR: {section}  (handle {root})")
            lines.append("=" * 72)
            stack = [(root, 0, True, "")]
        else:
            lines.append("")
            lines.append("=" * 72)
            lines.append(f"SECTOR: NODOS_SIN_RAIZ  (handle {root})")
            lines.append("=" * 72)
            counts["orphans"] += 1
            stack = [(root, 0, True, "")]
        while stack:
            h, depth, is_last, prefix = stack.pop()
            meta = nodes[h]
            t = meta.get("t")
            display = name_of(h)
            if depth == 0:
                lines.append(f"[{t}] {display}/")
            else:
                branch = "`-- " if is_last else "|-- "
                lines.append(
                    f"{prefix}{branch}[{TYPE_NAME.get(t, t)}] {display}"
                    + ("/" if t in (1, 2, 3, 4) else "")
                )
            kid_list = sort_children(children.get(h, []))
            if t in (1, 2, 3, 4):
                if t == 1:
                    counts["folders"] += 1 if depth else 0
                for i, k in enumerate(reversed(kid_list)):
                    is_last_child = i == 0
                    new_prefix = prefix + ("    " if is_last else "|   ")
                    stack.append((k, depth + 1, is_last_child, new_prefix))
            elif t == 0:
                counts["files"] += 1 if depth else 0

    header = []
    header.append("VOLCADO DE CONTENIDO DE CUENTA MEGA")
    header.append("=" * 72)
    header.append(f"Cuenta            : {EMAIL}")
    header.append(
        f"Fecha de volcado  : {datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')}"
    )
    header.append(f"Nodos totales     : {len(nodes)}")
    header.append(f"Archivos          : {counts['files']}")
    header.append(f"Carpetas          : {counts['folders']}")
    header.append(f"Nodos sin raíz    : {counts['orphans']}")
    header.append("Formato           : árbol, [0]=archivo [1]=carpeta")
    header.append("")

    body = header + lines + [""]

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(body))

    print(f"OK {len(body)} lineas -> {OUT}")


if __name__ == "__main__":
    main()
