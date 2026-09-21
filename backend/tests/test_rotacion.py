"""Rotación semanal de credenciales MEGA: misma biblioteca, otra cuenta.

Contrato del pipeline: da igual qué credenciales/cuenta se usen mientras
alcancen el MISMO share; el catálogo, las novedades y el enriquecimiento IGDB no
pueden moverse por rotar la cuenta. Y unas credenciales que no alcanzan los
datos deben fallar RUIDOSO, nunca vaciar la biblioteca.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.sync as sync_mod
from app.library import current_snapshot
from app.models import DownloadLink, Node, Title
from app.sync import frescura, fuente_volcado, refresh_text

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # el guard vive en el script del volcado
    sys.path.insert(0, str(REPO / "scripts"))

import refrescar_volcado as refresco  # noqa: E402

SHARE = "INSHARE biblioteca.demo@gmail.com:BCKP1"

CABECERA = (
    "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)\n"
    "=======================================================================\n"
    "Cuenta            : {cuenta}\n"
    "Fecha de volcado  : 2026-09-21T05:00:00+00:00\n"
    "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)\n"
)
SECTOR_SHARE = (
    "SECTOR: " + SHARE + "\n"
    "Archivos  : 2\n"
    "Carpetas  : 3\n"
    "Tamano    : 209715200 bytes\n"
    "\n"
    "[ROOT] //from/biblioteca.demo@gmail.com:BCKP1/\n"
    "|-- [FOLDER] -- A/\n"
    "|   `-- [FOLDER] Game One/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] game1.part1.rar  (104857600 bytes)\n"
)
SECTOR_NUBE_VACIA = (
    "SECTOR: CLOUD_DRIVE\n"
    "Archivos  : 0\n"
    "Carpetas  : 1\n"
    "Tamano    : 0 bytes (0 B)\n"
    "\n"
    "[ROOT] //\n"
    "`-- [FOLDER] S4 Object storage/\n"
)
# Otra cuenta que monta OTRO share: trae archivos, pero no la biblioteca.
SECTOR_OTRO = (
    "SECTOR: INSHARE otra.cuenta@gmail.com:OTRO\n"
    "Archivos  : 1\n"
    "Carpetas  : 2\n"
    "Tamano    : 1024 bytes\n"
    "\n"
    "[ROOT] //from/otra.cuenta@gmail.com:OTRO/\n"
    "|-- [FOLDER] -- A/\n"
    "|   `-- [FOLDER] Otro Juego/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] otro.part1.rar  (1024 bytes)\n"
)


def test_rotar_la_cuenta_no_mueve_el_catalogo(tmp_path):
    """Rotar credenciales (misma biblioteca) → 0 altas/bajas y 0 novedades."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    with Session(engine) as s:
        antes = {t.slug for t in s.execute(select(Title)).scalars()}

    rotado = SAMPLE_DUMP.replace(
        "Cuenta            : test@example.com", "Cuenta            : semana.nueva@example.com"
    )
    stats = refresh_text(engine, rotado)

    assert stats["added_files"] == 0
    assert stats["removed_files"] == 0
    assert stats["added_folders"] == 0
    assert stats["removed_folders"] == 0
    assert stats["novedades"] == 0

    with Session(engine) as s:
        assert current_snapshot(s).account == "semana.nueva@example.com"
        assert {t.slug for t in s.execute(select(Title)).scalars()} == antes


def test_rotar_la_cuenta_conserva_el_enriquecimiento_igdb(tmp_path):
    """El IGDB va por ruta/slug, así que la cuenta que volcó no lo afecta."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    with Session(engine) as s:
        zelda = next(t for t in s.execute(select(Title)).scalars() if "zelda" in t.slug)
        zelda.igdb_cover = "https://images.igdb.com/zelda.jpg"
        zelda.igdb_slug = "zelda-eow"
        s.commit()

    refresh_text(
        engine,
        SAMPLE_DUMP.replace(
            "Cuenta            : test@example.com", "Cuenta            : otra.semana@example.com"
        ),
    )

    with Session(engine) as s:
        zelda = s.execute(select(Title).where(Title.slug.like("%zelda%"))).scalar_one()
        assert zelda.igdb_cover == "https://images.igdb.com/zelda.jpg"
        assert zelda.igdb_slug == "zelda-eow"


def test_fuente_estable_independiente_de_la_cuenta(tmp_path):
    """La identidad del catálogo es el SHARE, no la cuenta que rota."""
    uno = tmp_path / "semana1.txt"
    dos = tmp_path / "semana2.txt"
    uno.write_text(CABECERA.format(cuenta="semana1@example.com") + SECTOR_SHARE, encoding="utf-8")
    dos.write_text(CABECERA.format(cuenta="semana2@example.com") + SECTOR_SHARE, encoding="utf-8")

    assert fuente_volcado(uno) == SHARE
    assert fuente_volcado(dos) == SHARE  # misma fuente con otra cuenta
    assert frescura(dos)["fuente"] == SHARE


def test_rotacion_de_share_remapa_rutas_y_conserva_igdb(tmp_path, monkeypatch):
    """Cambiar el share montado (BCKP1→BCKP2) NO reconstruye el catálogo."""
    monkeypatch.setattr(sync_mod, "MIN_RUTAS_ALIAS", 5)  # el volcado de muestra es pequeño
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    # Un enlace de descarga cacheado del share antiguo (debe reiniciarse).
    with Session(engine) as s:
        zelda = next(t for t in s.execute(select(Title)).scalars() if "zelda" in t.slug)
        zelda.igdb_cover = "https://images.igdb.com/zelda.jpg"
        nodo = s.execute(select(Node).where(Node.path.like("%zelda-eow%"))).scalars().first()
        s.add(
            DownloadLink(
                snapshot_id=zelda.snapshot_id,
                node_id=nodo.id,
                path=nodo.path,
                nivel="archivo",
                link="https://mega.nz/enlace-viejo",
                estado="ok",
            )
        )
        s.commit()
        ids_antes = {n.path: n.id for n in s.execute(select(Node)).scalars()}

    # Semana nueva: la MISMA biblioteca en otro share + 1 archivo realmente nuevo.
    rotado = (
        SAMPLE_DUMP.replace("INSHARE test@example.com:BCKP1", "INSHARE otro@example.com:BCKP2")
        .replace("//from/test@example.com:BCKP1", "//from/otro@example.com:BCKP2")
        .replace(
            "|           `-- [FILE] zelda-eow [v0][US](nsw2u.com).nsp  (55350596 bytes)",
            "|           |-- [FILE] zelda-eow [v0][US](nsw2u.com).nsp  (55350596 bytes)\n"
            "|           `-- [FILE] zelda-nuevo.nsp  (1024 bytes)",
        )
    )
    stats = refresh_text(engine, rotado)

    assert stats["rotados"] == [["INSHARE test@example.com:BCKP1", "INSHARE otro@example.com:BCKP2"]]
    assert stats["removed_files"] == 0
    assert stats["removed_folders"] == 0
    assert stats["added_files"] == 1  # solo el archivo nuevo de verdad
    assert stats["novedades"] == 1

    with Session(engine) as s:
        zelda = s.execute(select(Title).where(Title.slug.like("%zelda%"))).scalar_one()
        assert zelda.igdb_cover == "https://images.igdb.com/zelda.jpg"  # IGDB intacto

        nodos = {n.path: n.id for n in s.execute(select(Node)).scalars()}
        assert all("BCKP1" not in p for p in nodos)  # rutas remapadas
        # Los nodos que persisten conservan su id (no hubo borrado+alta).
        for viejo, node_id in ids_antes.items():
            nuevo_path = viejo.replace("BCKP1", "BCKP2").replace("test@", "otro@")
            if nuevo_path in nodos:
                assert nodos[nuevo_path] == node_id

        enlaces = s.execute(select(DownloadLink)).scalars().all()
        assert enlaces and all(e.estado == "pendiente" for e in enlaces)
        assert all(e.link is None for e in enlaces)


def test_sin_solape_no_se_considera_rotacion(tmp_path, monkeypatch):
    """Un share distinto con otra biblioteca NO se remapa (diff normal)."""
    monkeypatch.setattr(sync_mod, "MIN_RUTAS_ALIAS", 5)
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    otra = CABECERA.format(cuenta="otra@example.com") + SECTOR_OTRO
    stats = refresh_text(engine, otra, min_fraccion=0)
    assert stats["rotados"] == []
    assert stats["removed_files"] > 0  # se sustituye el contenido (comportamiento normal)


def test_sectores_con_archivos_ignora_los_vacios():
    texto = CABECERA.format(cuenta="a@b.c") + SECTOR_NUBE_VACIA + SECTOR_SHARE
    assert refresco.sectores_con_archivos(texto) == {SHARE}


def test_validar_sectores_detecta_credenciales_sin_acceso(tmp_path):
    """Si la cuenta nueva no monta la biblioteca, se detecta la pérdida."""
    viejo = tmp_path / "viejo.txt"
    viejo.write_text(
        CABECERA.format(cuenta="semana.pasada@example.com") + SECTOR_SHARE, encoding="utf-8"
    )
    sin_biblioteca = CABECERA.format(cuenta="semana.nueva@example.com") + SECTOR_OTRO

    # Sin solape suficiente no hay rotación que explique la pérdida → se aborta.
    perdidos, nuevos = refresco.validar_sectores_simples(
        viejo.read_text(encoding="utf-8"), sin_biblioteca
    )
    assert perdidos == [SHARE]
    assert nuevos == ["INSHARE otra.cuenta@gmail.com:OTRO"]
    assert refresco.validar_sectores(viejo, sin_biblioteca)[2] == []

    # Con las mismas credenciales alcanzando el mismo share no hay pérdida.
    igual = CABECERA.format(cuenta="semana.nueva@example.com") + SECTOR_SHARE
    assert refresco.validar_sectores(viejo, igual)[:2] == ([], [])


def test_rotacion_de_share_no_bloquea_el_refresco(tmp_path, monkeypatch):
    """El mismo contenido en otro share es una rotación, no una pérdida."""
    monkeypatch.setattr(sync_mod, "MIN_RUTAS_ALIAS", 5)  # volcado de muestra pequeño
    out = tmp_path / "volcado.txt"
    out.write_text(
        CABECERA.format(cuenta="semana.pasada@example.com") + SECTOR_SHARE, encoding="utf-8"
    )
    candidato = CABECERA.format(cuenta="semana.nueva@example.com") + SECTOR_SHARE.replace(
        "biblioteca.demo@gmail.com:BCKP1", "otro@example.com:BCKP2"
    )

    perdidos, _nuevos, rotados = refresco.validar_sectores(out, candidato)
    assert perdidos == [SHARE]
    assert rotados == [(SHARE, "INSHARE otro@example.com:BCKP2")]

    _main_stub(monkeypatch, candidato)
    monkeypatch.setattr(sys, "argv", ["refrescar_volcado.py", "--out", str(out), "--no-backup"])
    assert refresco.main() == 0  # no se bloquea: es la misma biblioteca
    assert out.read_text(encoding="utf-8") == candidato


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


def test_main_aborta_sin_escribir_si_se_pierde_la_biblioteca(tmp_path, monkeypatch, capsys):
    out = tmp_path / "volcado.txt"
    vigente = CABECERA.format(cuenta="semana.pasada@example.com") + SECTOR_SHARE
    out.write_text(vigente, encoding="utf-8")
    _main_stub(monkeypatch, CABECERA.format(cuenta="semana.nueva@example.com") + SECTOR_NUBE_VACIA)
    monkeypatch.setattr(sys, "argv", ["refrescar_volcado.py", "--out", str(out)])

    assert refresco.main() == 1
    assert out.read_text(encoding="utf-8") == vigente  # NO se escribe nada
    assert "NO trae estos sectores" in capsys.readouterr().out


def test_main_escribe_con_bandera_explicita(tmp_path, monkeypatch):
    out = tmp_path / "volcado.txt"
    out.write_text(
        CABECERA.format(cuenta="semana.pasada@example.com") + SECTOR_SHARE, encoding="utf-8"
    )
    candidato = CABECERA.format(cuenta="semana.nueva@example.com") + SECTOR_OTRO
    _main_stub(monkeypatch, candidato)
    monkeypatch.setattr(
        sys,
        "argv",
        ["refrescar_volcado.py", "--out", str(out), "--no-backup", "--permitir-sectores-perdidos"],
    )

    assert refresco.main() == 0
    assert out.read_text(encoding="utf-8") == candidato


@pytest.mark.parametrize("cuenta", ["cuenta.semana1@example.com", "cuenta.semana2@example.com"])
def test_cualquier_cuenta_del_flujo_produce_la_misma_fuente(cuenta, tmp_path):
    """Todas las cuentas de la rotación ven los mismos datos (mismo share)."""
    p = tmp_path / "v.txt"
    p.write_text(CABECERA.format(cuenta=cuenta) + SECTOR_SHARE, encoding="utf-8")
    assert fuente_volcado(p) == SHARE
