#!/usr/bin/env python3
"""Genera un volcado 'día +5' SIMULADO a partir del volcado canónico MEGA.

Sirve para auditar el flujo de actualización de producción SIN tocar la BD ni
el share real: añade un juego nuevo (B-ASE + U-PD), borra un archivo y cambia el
tamaño de otro (como pasaría 5 días después en la carpeta MEGA).

Uso (dentro del contenedor backend):
    PYTHONPATH=/app python /tmp/sim_dump_d5.py
Salida: /tmp/dump_d5.txt  +  /tmp/d5_manifest.json
"""
import json
from pathlib import Path

from app.parser import FILE, FOLDER, Node, parse_text

SRC = Path("/dump/mega_cuenta_contenido_MEGAcmd.txt")
OUT = Path("/tmp/dump_d5.txt")
MANIFEST = Path("/tmp/d5_manifest.json")

NUEVO_TITULO = "Aeternia Day Five Later"
BUCKET = "-- A"
TITLE_ID = "0100A1B2C3D4E5F6"  # 16 hex → detectable por versiones/ID


def main() -> None:
    d = parse_text(SRC.read_text(encoding="utf-8"))
    inshare = next(s for s in d.sectors if s.label.startswith("INSHARE"))
    root = inshare.roots[0]
    manifest: dict = {"nuevo_titulo": NUEVO_TITULO, "title_id": TITLE_ID}

    # 1) Borra un archivo existente (primer .part1.rar que encuentre).
    removed: list[str] = []

    def rm(nd) -> bool:
        for c in list(nd.children):
            if c.kind == FILE and "8453.part1.rar" in c.name and not removed:
                nd.children.remove(c)
                removed.append(c.name)
                return True
            if c.kind == FOLDER and rm(c):
                return True
        return False

    rm(root)
    manifest["archivo_borrado"] = removed[0] if removed else None

    # 2) Cambia el tamaño del primer archivo restante.
    changed: list[dict] = []

    def ch(nd) -> bool:
        for c in nd.children:
            if c.kind == FILE and not changed:
                changed.append({"nombre": c.name, "antes": c.size,
                                "despues": c.size + 1_234_567})
                c.size += 1_234_567
                return True
            if c.kind == FOLDER and ch(c):
                return True
        return False

    ch(root)
    manifest["archivo_cambiado"] = changed[0] if changed else None

    # 3) Añade un juego nuevo (título) dentro del bucket '-- A'.
    bucket = next(c for c in root.children if c.kind == FOLDER and c.name == BUCKET)
    titulo = Node(name=NUEVO_TITULO, kind=FOLDER, depth=2, parent=bucket)
    base = Node(name="B-ASE", kind=FOLDER, depth=3, parent=titulo)
    upd = Node(name="U-PD 1.2.0", kind=FOLDER, depth=3, parent=titulo)
    f1 = Node(name=f"{NUEVO_TITULO.lower()} {TITLE_ID}.nsp", kind=FILE, depth=4,
              size=6_801_234_567, parent=base)
    f2 = Node(name=f"{TITLE_ID} v1.2.0.nsp", kind=FILE, depth=4,
              size=312_345_678, parent=upd)
    titulo.children = [base, upd]
    base.children = [f1]
    upd.children = [f2]
    bucket.children.append(titulo)
    manifest["carpetas_nuevas"] = 3
    manifest["archivos_nuevos"] = 2

    # 4) Serializa al formato del parser (indent = depth*4).
    lineas: list[str] = [
        "CUENTA SIMULADA DÍA+5 (para auditoría de flujo de actualización)",
        "Cuenta            : dueno.demo.mega@gmail.com",
        "Fecha de volcado  : SIMULACIÓN +5 días",
        "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)",
        "",
    ]

    def escribir(n) -> None:
        for c in n.children:
            pref = " " * (4 * c.depth)
            if c.kind == FOLDER:
                lineas.append(f"{pref}[FOLDER] {c.name}/")
            else:
                lineas.append(f"{pref}[FILE] {c.name}  ({c.size} bytes)")
            if c.kind == FOLDER:
                escribir(c)

    for sec in d.sectors:
        lineas.append(f"SECTOR: {sec.label}")
        for r in sec.roots:
            lineas.append(f"[ROOT] {sec.label}/")
            escribir(r)

    OUT.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    # Validación: re-parsear la salida.
    v = parse_text(OUT.read_text(encoding="utf-8"))
    hay = any(t2.name == NUEVO_TITULO
              for b in v.sectors for r in b.roots for c in r.children
              if c.kind == FOLDER for t2 in c.children)
    print("OK ->", OUT)
    print("manifest:", json.dumps(manifest, ensure_ascii=False))
    print("reparse totals:", v.totals(), "| titulo presente:", hay)


if __name__ == "__main__":
    main()
