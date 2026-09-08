"""Tests del escaneo incremental (sync): diff sin reconstruir la BD."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.library import current_snapshot
from app.models import Node, SyncLog, Title
from app.sync import refresh_text

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP
from .test_igdb import _procesar_stub
from app.enrich import run as enrich_run

# Volcado "vacío" (solo carpetas, 0 archivos) → el guard debe abortar.
TEXTO_SIN_ARCHIVOS = (
    "SECTOR: INSHARE test@example.com:BCKP1\n"
    "[ROOT] INSHARE test@example.com:BCKP1/\n"
    "    [FOLDER] -- A/\n"
    "        [FOLDER] Solo Carpetas/\n"
    "            [FOLDER] B-ASE/\n"
)

BLOQUE_DLC = (
    "|   |   |-- [FOLDER] D-LC/\n"
    "|   |   |   `-- [FILE] game1.dlc1.part1.rar  (1024 bytes)\n"
)
SECTOR_Z_VIEJO = (
    "|-- [FOLDER] -- Z/\n"
    "|   `-- [FOLDER] Zelda Echoes of Wisdom/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] zelda-eow [v0][US](nsw2u.com).nsp  (55350596 bytes)\n"
)
SECTOR_Z_NUEVO = (
    "|-- [FOLDER] -- Z/\n"
    "|   |-- [FOLDER] Zelda Echoes of Wisdom/\n"
    "|   |   `-- [FOLDER] B-ASE/\n"
    "|   |       `-- [FILE] zelda-eow [v0][US](nsw2u.com).nsp  (55350596 bytes)\n"
    "|   `-- [FOLDER] Zoo Tycoon Plus/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] zoo.part1.rar  (123456789 bytes)\n"
)


def _cambiar(texto: str) -> str:
    texto = texto.replace(
        "game1.part1.rar  (104857600 bytes)",
        "game1.part1.rar  (104999999 bytes)",
    )
    # SUSTRACCIÓN de prueba: se elimina la carpeta D-LC y su archivo.
    salida = []
    saltar = False
    for linea in texto.splitlines():
        if not saltar and "[FOLDER] D-LC/" in linea:
            saltar = True
            continue
        if saltar:  # el archivo hijo de D-LC
            saltar = False
            continue
        salida.append(linea)
    texto = "\n".join(salida) + "\n"
    assert SECTOR_Z_VIEJO in texto
    texto = texto.replace(SECTOR_Z_VIEJO, SECTOR_Z_NUEVO)
    return texto


def test_sync_incremental_suma_y_resta_sin_reconstruir(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    # Enriquecer Zelda (para comprobar que el sync conserva los datos IGDB).
    enrich_run(engine, procesar=_procesar_stub)

    stats = refresh_text(engine, _cambiar(SAMPLE_DUMP))
    assert stats["removed_files"] == 1            # game1.dlc1…
    assert stats["removed_folders"] == 1          # D-LC
    assert stats["added_files"] == 1              # zoo.part1.rar
    assert stats["added_folders"] == 2            # Zoo Tycoon Plus + B-ASE
    assert stats["changed_files"] == 1            # game1.part1.rar tamaño
    assert stats["bootstrap"] is False

    with Session(engine) as session:
        snap = current_snapshot(session)
        sid = snap.id
        from app.models import Snapshot

        assert session.get(Snapshot, sid).file_count == 6  # -1 (dlc) +1 (zoo)

        nodos = session.execute(
            select(Node).where(Node.snapshot_id == sid)
        ).scalars().all()
        rutas = {n.path for n in nodos}
        # Sustracción aplicada y adición aplicada.
        assert not any("game1.dlc1" in p for p in rutas)
        assert any(p.endswith("/Zoo Tycoon Plus/B-ASE/zoo.part1.rar") for p in rutas)

        titulos = {
            t.name: t
            for t in session.execute(
                select(Title).where(Title.snapshot_id == sid)
            ).scalars()
        }
        assert set(titulos) == {
            "A Game One", "A Second Game", "Zelda Echoes of Wisdom", "Zoo Tycoon Plus",
        }
        zelda = titulos["Zelda Echoes of Wisdom"]
        # El enriquecimiento IGDB se CONSERVA.
        assert zelda.igdb_cover == "https://images.igdb.com/c.jpg"
        assert zelda.igdb_slug == "zelda-eow"

        # El título que perdió el DLC se actualiza (derivado), sin borrarse.
        game = titulos["A Game One"]
        assert game.dlc_count == 0
        assert game.file_count == 3

        zoo = titulos["Zoo Tycoon Plus"]
        assert zoo.base_count == 1
        assert zoo.file_count == 1

        # Quedó registrado un escaneo con el diff.
        logs = session.execute(select(SyncLog)).scalars().all()
        assert len(logs) == 1
        assert logs[0].removed_files == 1
        assert logs[0].added_folders == 2


def test_sync_idempotente_sin_cambios(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    stats = refresh_text(engine, SAMPLE_DUMP)
    assert stats["added_files"] == 0
    assert stats["removed_files"] == 0
    assert stats["changed_files"] == 0
    assert stats["removed_folders"] == 0

def test_sync_volcado_vacio_no_borra(tmp_path):
    """Blindaje: un volcado sin archivos NUNCA vacía la biblioteca por error."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    with Session(engine) as s:
        antes = s.execute(select(Node)).scalars().all()

    with pytest.raises(RuntimeError, match="ABORTA"):
        refresh_text(engine, TEXTO_SIN_ARCHIVOS)

    # La BD sigue intacta.
    with Session(engine) as s:
        despues = s.execute(select(Node)).scalars().all()
        assert len(despues) == len(antes)
        assert s.execute(select(Title)).scalars().all()  # títulos siguen


def test_sync_volcado_vacio_con_allow_forzado(tmp_path):
    """Solo con allow_empty=True se aplica un vaciado consciente."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    stats = refresh_text(engine, TEXTO_SIN_ARCHIVOS, allow_empty=True)
    assert stats["bootstrap"] is False
    assert stats["total_files"] == 0
    assert stats["removed_files"] > 0



def test_router_sync_dump_vacio_devuelve_400_y_no_toca_bd(tmp_path):
    """Blindaje de API: POST /api/sync/dump con un volcado sin archivos → 400."""
    from fastapi.testclient import TestClient

    app = build_app(tmp_path, SAMPLE_DUMP)
    vacio = tmp_path / "vacio.txt"
    vacio.write_text(
        "SECTOR: INSHARE x:BCKP1\n"
        "[ROOT] INSHARE x:BCKP1/\n"
        "    [FOLDER] -- A/\n",
        encoding="utf-8",
    )
    with TestClient(app) as c:
        r = c.post("/api/sync/dump", json={"path": str(vacio)})
    assert r.status_code == 400
    assert "ABORTA" in r.json()["detail"]

    with Session(app.state.engine) as s:
        assert s.execute(select(Title)).scalars().all()  # BD intacta
