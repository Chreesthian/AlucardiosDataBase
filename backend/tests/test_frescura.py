"""Tests de la frescura del volcado (fallo rápido y ruidoso del pipeline).

Cubre el hueco que dejaba el desfase silencioso: el vigía `app.sync --watch` no
puede refrescar la fuente, así que debe DETECTAR un volcado caducado, quejarse y
salir con error en vez de repetir "sin cambios" para siempre.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sync import (
    EXIT_VOLCADO_OBSOLETO,
    comprobar_frescura,
    fecha_generada,
    frescura,
    refresh_text,
)

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

CABECERA = (
    "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)\n"
    "=======================================================================\n"
    "Cuenta            : test@example.com\n"
    "Fecha de volcado  : {fecha}\n"
    "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)\n"
    "\n"
)


# Cuerpo sin cabecera: así se prueba la caída al `mtime` (el SAMPLE_DUMP real
# sí trae su propia línea "Fecha de volcado").
CUERPO_SIN_FECHA = (
    "SECTOR: INSHARE test@example.com:BCKP1\n"
    "[ROOT] INSHARE test@example.com:BCKP1/\n"
    "|-- [FOLDER] -- A/\n"
    "|   `-- [FOLDER] Game One/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] game1.part1.rar  (104857600 bytes)\n"
)


def _dump(tmp_path, *, horas: float | None, con_cabecera: bool = True, cuerpo: str = SAMPLE_DUMP):
    """Volcado de prueba con la cabecera a `horas` de antigüedad."""
    texto = cuerpo
    if con_cabecera and horas is not None:
        fecha = (datetime.now(UTC) - timedelta(hours=horas)).isoformat(timespec="seconds")
        texto = CABECERA.format(fecha=fecha) + SAMPLE_DUMP
    p = tmp_path / "volcado.txt"
    p.write_text(texto, encoding="utf-8")
    if horas is not None and not con_cabecera:  # sin cabecera: se usa el mtime
        sello = (datetime.now(UTC) - timedelta(hours=horas)).timestamp()
        os.utime(p, (sello, sello))
    return p


def _app(tmp_path, dump):
    cfg = Settings(
        database_url=f"sqlite:///{tmp_path / 'frescura.db'}",
        dump_path=str(dump),
        sync_max_edad_horas=26,
    )
    return create_app(cfg)


def test_fecha_generada_lee_la_cabecera(tmp_path):
    """La fecha de la cabecera la reescribe el volcador: es la fuente de verdad."""
    p = _dump(tmp_path, horas=1.0)
    assert fecha_generada(p) is not None


def test_sin_cabecera_no_hay_fecha(tmp_path):
    p = _dump(tmp_path, horas=None, con_cabecera=False, cuerpo=CUERPO_SIN_FECHA)
    assert fecha_generada(p) is None


def test_volcado_reciente_no_es_obsoleto(tmp_path):
    p = _dump(tmp_path, horas=1.5)
    info = frescura(p, 26)
    assert info["origen"] == "cabecera"
    assert info["edad_horas"] == pytest.approx(1.5, abs=0.2)
    assert info["obsoleto"] is False
    assert comprobar_frescura(p, 26) == 0


def test_volcado_caducado_avisa_y_sale_con_error(tmp_path, caplog):
    """El caso real del desfase: volcado de hace días → rc != 0 y CRITICAL."""
    p = _dump(tmp_path, horas=170.0)
    info = frescura(p, 26)
    assert info["obsoleto"] is True
    assert info["edad_horas"] == pytest.approx(170.0, abs=0.5)

    with caplog.at_level("CRITICAL"):
        assert comprobar_frescura(p, 26) == EXIT_VOLCADO_OBSOLETO
    assert "VOLCADO OBSOLETO" in caplog.text
    # `make volcado` / `make volcado-cron` aparecen en el aviso para poder actuar.
    assert "make volcado" in caplog.text


def test_volcado_caducado_tolerado_solo_avisa(tmp_path, caplog):
    """Escaneo manual: se avisa (ERROR) pero no se aborta."""
    p = _dump(tmp_path, horas=170.0)
    with caplog.at_level("ERROR"):
        assert comprobar_frescura(p, 26, tolerar=True) == 0
    assert "VOLCADO OBSOLETO" in caplog.text


def test_max_edad_cero_desactiva_el_guard(tmp_path):
    p = _dump(tmp_path, horas=500.0)
    assert frescura(p, 0)["obsoleto"] is False
    assert comprobar_frescura(p, 0) == 0


def test_sin_cabecera_cae_al_mtime(tmp_path):
    """Volcados hechos a mano (o antiguos) se miden por fecha del fichero."""
    p = _dump(tmp_path, horas=50.0, con_cabecera=False, cuerpo=CUERPO_SIN_FECHA)
    info = frescura(p, 26)
    assert info["origen"] == "mtime"
    assert info["edad_horas"] == pytest.approx(50.0, abs=0.2)
    assert info["obsoleto"] is True


def test_api_sync_status_expone_la_frescura(tmp_path):
    """/api/sync/status dice si la fuente está caducada (la UI avisa con esto)."""
    viejo = _dump(tmp_path, horas=170.0)
    with TestClient(_app(tmp_path, viejo)) as c:
        body = c.get("/api/sync/status").json()
    assert body["dump_exists"] is True
    assert body["dump_obsoleto"] is True
    assert body["dump_max_edad_horas"] == 26
    assert body["dump_age_hours"] == pytest.approx(170.0, abs=0.5)

    fresco = _dump(tmp_path, horas=2.0)
    with TestClient(_app(tmp_path, fresco)) as c:
        body = c.get("/api/sync/status").json()
    assert body["dump_obsoleto"] is False
    assert body["dump_age_hours"] == pytest.approx(2.0, abs=0.2)


def test_sync_aborta_volcado_truncado(tmp_path):
    """Blindaje anti-escritura a medias: una caída masiva de archivos se aborta."""
    app = build_app(tmp_path, SAMPLE_DUMP)  # 6 archivos en el volcado de muestra
    solo_uno = (
        "SECTOR: INSHARE test@example.com:BCKP1\n"
        "[ROOT] INSHARE test@example.com:BCKP1/\n"
        "|-- [FOLDER] -- A/\n"
        "|   `-- [FOLDER] Game One/\n"
        "|       `-- [FOLDER] B-ASE/\n"
        "|           `-- [FILE] game1.part1.rar  (104857600 bytes)\n"
    )
    with pytest.raises(RuntimeError, match="Volcado sospechoso"):
        refresh_text(app.state.engine, solo_uno)
    # Con el guard desactivado (bajada consciente) sí se aplica.
    stats = refresh_text(app.state.engine, solo_uno, min_fraccion=0)
    assert stats["removed_files"] > 0
