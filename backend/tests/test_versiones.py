"""Tests de auditoría de versiones (local vs Nintendo)."""

from app.versiones import parse_version, title_id_de_nombre, vers_a_texto


def test_parse_version_folder():
    assert parse_version("U-PD 1.2.5") == (1, 2, 5)
    assert parse_version("UP-D 1.0.1") == (1, 0, 1)
    assert parse_version("B-ASE") is None
    assert parse_version("D-LC") is None
    assert vers_a_texto((1, 12, 3)) == "1.12.3"


def test_title_id_de_nombre():
    assert title_id_de_nombre(
        "Arcade Archives CUE BRICK [010066001E178000][v0][US](nsw2u.com).nsp"
    ) == "010066001E178000"
    assert title_id_de_nombre("juego.part1.rar") is None
