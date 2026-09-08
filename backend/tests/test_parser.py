"""Test del parser del volcado MEGAcmd."""

from __future__ import annotations

from app.parser import FOLDER, parse_text

from .sample_dump import SAMPLE_DUMP


def test_cabecera_global():
    dump = parse_text(SAMPLE_DUMP)
    assert dump.account == "test@example.com"
    assert dump.generated_at == "2026-09-07T00:00:00"
    assert dump.tool.startswith("MEGAcmd")


def test_conteos_globales():
    dump = parse_text(SAMPLE_DUMP)
    assert dump.file_count == 6
    assert dump.folder_count == 12  # 10 en INSHARE + 1 CLOUD + 1 INBOX


def test_sectores_y_arbol_inshare():
    dump = parse_text(SAMPLE_DUMP)
    assert [s.label for s in dump.sectors] == [
        "CLOUD_DRIVE",
        "INBOX",
        "RUBBISH_BIN",
        "INSHARE test@example.com:BCKP1",
    ]
    inshare = dump.sectors[3]
    assert len(inshare.roots) == 1
    root = inshare.roots[0]
    assert root.total_files == 6
    assert root.total_folders == 10
    buckets = [c for c in root.children if c.is_folder]
    assert [b.name for b in buckets] == ["-- A", "-- Z"]


def test_estructura_titulo_y_archivos():
    dump = parse_text(SAMPLE_DUMP)
    inshare = dump.sectors[3].roots[0]
    bucket_a = inshare.children[0]
    game_one = bucket_a.children[0]
    assert game_one.name == "A Game One"
    assert game_one.is_folder
    assert game_one.total_size == 214959104  # 104857600+104857600+5242880+1024
    assert game_one.total_files == 4

    versions = [c for c in game_one.children if c.is_folder]
    assert [v.name for v in versions] == ["B-ASE", "U-PD 1.0.1", "D-LC"]
    rar = [f for f in versions[0].children if f.name.endswith("part1.rar")][0]
    assert rar.size == 104857600
    assert rar.ext == "rar"


def test_extension_nsp():
    dump = parse_text(SAMPLE_DUMP)
    zelda = dump.sectors[3].roots[0].children[1].children[0]
    (nsp,) = [f for f in zelda.children[0].children]
    assert nsp.ext == "nsp"
