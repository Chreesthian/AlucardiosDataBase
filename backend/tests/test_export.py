"""Tests de la exportación completa de la biblioteca (`app.exportdb`).

Cubren la regresión que dejaba a `backend-sync --export` en bucle de fallos: el
recorrido de archivos de cada versión debe descender por el mapa global
``parent_id -> [nodos]``. Al indexar cada nodo por su propio id se entraba en
recursión infinita (`RecursionError`) en cuanto un título tenía carpetas de
versión, que es el caso de toda la biblioteca real.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.exportdb import export

from .conftest import build_app

# Versión con una subcarpeta intermedia: fuerza a descender más de un nivel.
DUMP_ANIDADO = """\
VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)
========================================================================
Cuenta            : test@example.com
Fecha de volcado  : 2026-09-07T00:00:00
Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)
Archivos          : 2
Carpetas          : 3
Tamano total      : 2048 bytes

========================================================================
SECTOR: INSHARE test@example.com:BCKP1
========================================================================
Archivos  : 2
Carpetas  : 3
Tamano    : 2048 bytes (2 KB)

[ROOT] //from/test@example.com:BCKP1/
|-- [FOLDER] -- A/
|   `-- [FOLDER] A Game One/
|       `-- [FOLDER] B-ASE/
|           `-- [FOLDER] Sub/
|               |-- [FILE] game1.sub.part1.rar  (1024 bytes)
|               `-- [FILE] game1.sub.part2.rar  (1024 bytes)
"""


def _exportar(app, out: Path) -> dict:
    export(app.state.engine, out=out)
    return json.loads(out.read_text(encoding="utf-8"))


def test_export_estructura_por_versiones(client, tmp_path):
    data = _exportar(client.app, tmp_path / "biblioteca.json")

    juegos = {g["nombre"]: g for g in data["juegos"]}
    assert set(juegos) == {"A Game One", "A Second Game", "Zelda Echoes of Wisdom"}

    versiones = {v["nombre"]: v for v in juegos["A Game One"]["local"]["versiones"]}
    assert set(versiones) == {"B-ASE", "U-PD 1.0.1", "D-LC"}
    assert versiones["B-ASE"]["tipo"] == "base"
    assert versiones["U-PD 1.0.1"]["tipo"] == "update"
    assert versiones["D-LC"]["tipo"] == "dlc"

    base = versiones["B-ASE"]["contenido"]
    assert [(f["nombre"], f["ruta"], f["ext"], f["tamano"]) for f in base] == [
        ("game1.part1.rar", "B-ASE/game1.part1.rar", "rar", 104857600),
        ("game1.part2.rar", "B-ASE/game1.part2.rar", "rar", 104857600),
    ]
    assert [f["nombre"] for f in versiones["U-PD 1.0.1"]["contenido"]] == ["game1.101.part1.rar"]
    assert [f["nombre"] for f in versiones["D-LC"]["contenido"]] == ["game1.dlc1.part1.rar"]


def test_export_desciende_subcarpetas_de_version(tmp_path):
    app = build_app(tmp_path, text=DUMP_ANIDADO)
    data = _exportar(app, tmp_path / "anidado.json")

    assert data["meta"]["total_juegos"] == 1
    juego = data["juegos"][0]
    assert juego["nombre"] == "A Game One"

    (version,) = juego["local"]["versiones"]
    assert version["nombre"] == "B-ASE"
    assert [f["ruta"] for f in version["contenido"]] == [
        "B-ASE/Sub/game1.sub.part1.rar",
        "B-ASE/Sub/game1.sub.part2.rar",
    ]
