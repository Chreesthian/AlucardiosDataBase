"""Tests de escritura atómica (anti-JSON corrupto si el proceso cae a mitad)."""
from __future__ import annotations

import json

from app.safefs import atomic_write_text


def test_atomic_write_text_sustituye_y_no_deja_tmp(tmp_path):
    destino = tmp_path / "out.json"
    atomic_write_text(destino, json.dumps({"v": 1}))
    assert json.loads(destino.read_text(encoding="utf-8")) == {"v": 1}
    # No quedan ficheros temporales huérfanos.
    restos = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert restos == []


def test_atomic_write_text_sobrescribe(tmp_path):
    destino = tmp_path / "out.json"
    atomic_write_text(destino, "1")
    atomic_write_text(destino, "2")
    assert destino.read_text(encoding="utf-8") == "2"
