"""Cobertura de la biblioteca: perder TÍTULOS no puede pasar desapercibido.

El guard de archivos no cubre el caso real que apareció con la rotación de
credenciales: un share re-compartido a medias (o una cuenta que ve menos buckets)
trae archivos de sobra pero MENOS juegos, así que el catálogo se mutilaba en
silencio (títulos y su enriquecimiento IGDB a la basura) sin que ningún guard se
quejara. El contrato se fija en los tres puntos donde se puede cortar:

1. el recuento canónico (`app.ingest.contar_titulos*`),
2. la aplicación del volcado (`app.sync.refresh`, blindaje 3),
3. el script del host (`refrescar_volcado.validar_titulos`).

Vocabulario: "título" = carpeta de juego que cuelga de un bucket (mismo criterio
que `app.ingest.role_of`, es decir que las filas `Node.role == "title"`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest import contar_titulos, contar_titulos_por_sector
from app.models import Title
from app.parser import parse_text
from app.sync import refresh_text

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # el guard vive en el script del volcado
    sys.path.insert(0, str(REPO / "scripts"))

import refrescar_volcado as refresco  # noqa: E402

SHARE = "INSHARE test@example.com:BCKP1"
# El mismo share con las mismas etiquetas de sector, pero sin el juego "-- Z/"
# (dos títulos en vez de tres): exactamente el share re-compartido a medias.
SIN_ZELDA = SAMPLE_DUMP.split("|-- [FOLDER] -- Z/")[0]


def _titulos(engine) -> set[str]:
    with Session(engine) as s:
        return {t.slug for t in s.execute(select(Title)).scalars()}


def test_contar_titulos_del_volcado_de_muestra():
    """El recuento canónico no necesita BD y respeta la jerarquía del volcado."""
    parsed = parse_text(SAMPLE_DUMP)
    assert contar_titulos(parsed) == 3
    assert contar_titulos_por_sector(parsed) == {
        "CLOUD_DRIVE": 0,  # carpetas sueltas de la nube, no son juegos
        "INBOX": 0,
        "RUBBISH_BIN": 0,
        SHARE: 3,  # A Game One, A Second Game, Zelda Echoes of Wisdom
    }


def test_volcado_con_menos_titulos_se_aborta(tmp_path):
    """Caída de títulos → RuntimeError ANTES del diff (la BD queda intacta)."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    antes = _titulos(engine)

    with pytest.raises(RuntimeError, match="Volcado incompleto"):
        refresh_text(engine, SIN_ZELDA)

    assert _titulos(engine) == antes  # nada borrado


def test_titulos_se_pueden_aplicar_con_fraccion_desactivada(tmp_path):
    """`--min-titulos-fraccion 0` es la válvula para bajadas intencionadas."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    stats = refresh_text(engine, SIN_ZELDA, min_titulos_fraccion=0)
    assert stats["removed_files"] == 1  # el .nsp del juego retirado
    assert not any("zelda" in slug.lower() for slug in _titulos(engine))


def test_umbral_por_defecto_no_frena_lo_legitimo(tmp_path):
    """Un volcado con los mismos títulos (rotación de cuenta) se aplica igual."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    # Solo cambia la cuenta que volcó: el share y los títulos son los mismos.
    rotado = SAMPLE_DUMP.replace(
        "Cuenta            : test@example.com", "Cuenta            : semana.nueva@example.com"
    )

    stats = refresh_text(engine, rotado)
    assert stats["added_files"] == stats["removed_files"] == 0
    assert len(_titulos(engine)) == 3


def test_validar_titulos_del_script_del_host(tmp_path):
    """El host corta antes de escribir el volcado (y no bloquea sin vigente)."""
    out = tmp_path / "volcado.txt"
    assert refresco.validar_titulos(out, SIN_ZELDA, 0.9) == (True, "")  # sin vigente

    out.write_text(SAMPLE_DUMP, encoding="utf-8")
    ok, detalle = refresco.validar_titulos(out, SIN_ZELDA, 0.9)
    assert ok is False
    assert "2 títulos frente a 3" in detalle

    ok, detalle = refresco.validar_titulos(out, SAMPLE_DUMP, 0.9)
    assert ok is True and "3" in detalle

    assert refresco.validar_titulos(out, SIN_ZELDA, 0)[0] is True  # desactivado


def test_main_aborta_sin_escribir_si_pierde_titulos(tmp_path, monkeypatch, capsys):
    out = tmp_path / "volcado.txt"
    out.write_text(SAMPLE_DUMP, encoding="utf-8")
    _main_stub(monkeypatch, SIN_ZELDA)
    monkeypatch.setattr(sys, "argv", ["refrescar_volcado.py", "--out", str(out)])

    assert refresco.main() == 1
    assert out.read_text(encoding="utf-8") == SAMPLE_DUMP  # NO se escribe nada
    assert "títulos" in capsys.readouterr().out


def test_main_escribe_con_permitir_titulos_perdidos(tmp_path, monkeypatch):
    out = tmp_path / "volcado.txt"
    out.write_text(SAMPLE_DUMP, encoding="utf-8")
    _main_stub(monkeypatch, SIN_ZELDA)
    monkeypatch.setattr(
        sys,
        "argv",
        ["refrescar_volcado.py", "--out", str(out), "--no-backup", "--permitir-titulos-perdidos"],
    )

    assert refresco.main() == 0
    assert out.read_text(encoding="utf-8") == SIN_ZELDA


def test_router_sync_dump_devuelve_400_si_pierde_titulos(tmp_path):
    """La API propaga el blindaje 3 como 400: ni 500 ni catálogo mutilado.

    `autovolcado.sh` dispara el escaneo por HTTP, así que el guard tiene que
    viajar por el router con el umbral de `settings`, no solo por la CLI.
    """
    from fastapi.testclient import TestClient

    app = build_app(tmp_path, SAMPLE_DUMP)
    candidato = tmp_path / "dump.txt"
    candidato.write_text(SIN_ZELDA, encoding="utf-8")

    with TestClient(app) as c:
        r = c.post("/api/sync/dump", json={"path": str(candidato)})

    assert r.status_code == 400, r.text
    assert "títulos" in r.json()["detail"]
    assert len(_titulos(app.state.engine)) == 3  # el catálogo queda intacto


def _main_stub(monkeypatch, texto_candidato: str):
    """Main con MEGAcmd simulado: devuelve siempre el candidato indicado."""
    monkeypatch.setattr(refresco, "cuenta_activa", lambda *_a, **_k: "semana.nueva@example.com")
    monkeypatch.setattr(refresco, "sectores", lambda *_a, **_k: [("CLOUD_DRIVE", "/", "/")])
    monkeypatch.setattr(refresco, "volcar_listados", lambda *_a, **_k: {})
    monkeypatch.setattr(
        refresco,
        "construir_volcado",
        lambda *_a, **_k: (texto_candidato, {"files": 0, "folders": 1, "bytes": 0}),
    )
