"""Tests de la sección "Novedades": registro, clasificación, consultas y API."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Novedad
from app.novedades import listar, reconstruir, resumen, serializar, tipo_de
from app.sync import refresh_text

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

# Bloque de la actualización existente en el volcado de muestra (A Game One).
BLOQUE_UD101 = (
    "|   |   |-- [FOLDER] U-PD 1.0.1/\n"
    "|   |   |   `-- [FILE] game1.101.part1.rar  (5242880 bytes)\n"
)
# Actualización NUEVA sobre un título que ya existe.
UD_NUEVA = (
    "|   |   |-- [FOLDER] U-PD 1.0.2/\n"
    "|   |   |   `-- [FILE] game1.102.part1.rar  (1048576 bytes)\n"
)
# Juego NUEVO (bucket nuevo -- N) con su contenido base.
JUEGO_NUEVO = (
    "|-- [FOLDER] -- N/\n"
    "|   `-- [FOLDER] New Shiny Game/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] shiny.part1.rar  (2048 bytes)\n"
)


def _con_novedades(texto: str) -> str:
    return texto.replace(BLOQUE_UD101, BLOQUE_UD101 + UD_NUEVA) + JUEGO_NUEVO


def test_tipo_de_clasifica_versiones():
    assert tipo_de(None, titulo_nuevo=True) == "juego_nuevo"
    assert tipo_de(None, titulo_nuevo=False) == "contenido_nuevo"
    assert tipo_de("U-PD 1.3.0", titulo_nuevo=False) == "update_nuevo"
    assert tipo_de("2 D-LC", titulo_nuevo=False) == "dlc_nuevo"
    assert tipo_de("B-ASE", titulo_nuevo=False) == "contenido_nuevo"


def test_sync_registra_juego_nuevo_y_actualizacion(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    stats = refresh_text(engine, _con_novedades(SAMPLE_DUMP))
    assert stats["novedades"] == 2

    with Session(engine) as s:
        filas = s.execute(select(Novedad)).scalars().all()
    por_clave = {(f.tipo, f.slug): f for f in filas}

    juego = por_clave[("juego_nuevo", "new-shiny-game")]
    assert juego.name == "New Shiny Game"
    assert juego.letter == "N"
    assert juego.version is None
    assert juego.archivos == 1
    assert juego.bytes_nuevos == 2048
    assert juego.detalle_json == '["B-ASE/shiny.part1.rar"]'

    act = por_clave[("update_nuevo", "a-game-one")]
    assert act.name == "A Game One"
    assert act.version == "U-PD 1.0.2"
    assert act.archivos == 1
    assert act.bytes_nuevos == 1048576
    assert act.detalle_json == '["U-PD 1.0.2/game1.102.part1.rar"]'


def test_novedades_no_se_duplican_al_reescanear(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    texto = _con_novedades(SAMPLE_DUMP)

    refresh_text(engine, texto)
    stats = refresh_text(engine, texto)  # sin diff de árbol

    assert stats["novedades"] == 0
    with Session(engine) as s:
        assert len(s.execute(select(Novedad)).scalars().all()) == 2


def test_api_novedades_vacia_sin_eventos(client):
    data = client.get("/api/novedades").json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["resumen"]["total"] == 0


def test_api_novedades_lista_hidrata_y_filtra(tmp_path):
    from fastapi.testclient import TestClient

    app = build_app(tmp_path, SAMPLE_DUMP)
    refresh_text(app.state.engine, _con_novedades(SAMPLE_DUMP))

    with TestClient(app) as c:
        data = c.get("/api/novedades").json()
        assert data["total"] == 2
        assert data["resumen"]["juegos_nuevos"] == 1
        assert data["resumen"]["actualizaciones"] == 1

        juego = next(i for i in data["items"] if i["tipo"] == "juego_nuevo")
        assert juego["titulo"]["name"] == "New Shiny Game"  # hidratado con la biblioteca
        assert juego["titulo"]["base_count"] == 1
        assert juego["vigente"] is True
        assert juego["detalle"] == ["B-ASE/shiny.part1.rar"]

        filtrado = c.get("/api/novedades", params={"tipo": "update_nuevo"}).json()
        assert filtrado["total"] == 1
        assert filtrado["items"][0]["version"] == "U-PD 1.0.2"
        assert filtrado["items"][0]["slug"] == "a-game-one"


def test_reconstruir_periodo_desde_dos_volcados(tmp_path):
    """`--desde/--hasta` reconstruye las novedades de un periodo ya pasado."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    viejo = tmp_path / "volcado_anterior.txt"
    viejo.write_text(SAMPLE_DUMP, encoding="utf-8")
    nuevo = tmp_path / "volcado_nuevo.txt"
    nuevo.write_text(_con_novedades(SAMPLE_DUMP), encoding="utf-8")

    with Session(engine) as s:
        creados = reconstruir(s, 1, viejo, nuevo, fecha="2026-09-14T09:32:16+00:00")
        s.commit()
        filas, total = listar(s, snapshot_id=1)
        res = resumen(s, snapshot_id=1)
        items = serializar(s, 1, filas)

        # Repetir la reconstrucción es idempotente: no duplica contadores.
        repetidos = reconstruir(s, 1, viejo, nuevo, fecha="2026-09-14T09:32:16+00:00")
        s.commit()
        filas2, total2 = listar(s, snapshot_id=1)
        juego = next(f for f in filas2 if f.tipo == "juego_nuevo")

    assert creados == 2
    assert repetidos == 0
    assert total == total2 == 2
    assert juego.archivos == 1
    assert res["por_tipo"]["juego_nuevo"] == 1
    assert res["por_tipo"]["update_nuevo"] == 1
    assert {f.detectada_en.date().isoformat() for f in filas} == {"2026-09-14"}
    # El payload del export debe ser serializable tal cual (regresión).
    json.dumps(items)
