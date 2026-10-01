"""Fixtures compartidos: app con BD temporal y volcado de muestra ingerido.

Cada colección usa SU PROPIA BD: `test.db` (Switch) y `retro.db` (ROMs). Las dos
viven en `tmp_path`, así que los tests nunca tocan los datos del repo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest import COLECCION_RETRO, ingest
from app.main import create_app
from app.parser import parse_text

from .sample_dump import SAMPLE_DUMP
from .sample_dump_retro import SAMPLE_DUMP_RETRO


def build_app(tmp_path, text: str = SAMPLE_DUMP, retro_text: str | None = None):
    db = tmp_path / "test.db"
    retro_db = tmp_path / "retro.db"
    cfg = Settings(
        database_url=f"sqlite:///{db}",
        retro_database_url=f"sqlite:///{retro_db}",
        # El volcado retro por defecto apunta al repo; en tests, a un temporal.
        retro_dump_path=tmp_path / "mega_retro.txt",
    )
    app = create_app(cfg)

    ingest(app.state.engine, parse_text(text), source_kind="dump", source_path=":memory-sample:")
    if retro_text is not None:
        ingest(
            app.state.engine_retro,
            parse_text(retro_text),
            source_kind="dump",
            source_path=":memory-retro:",
            coleccion=COLECCION_RETRO,
        )
    return app


def build_app_retro(tmp_path):
    """App con el catálogo Switch Y la colección retro ya ingeridos."""
    return build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)


@pytest.fixture()
def client(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_retro(tmp_path):
    app = build_app_retro(tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_text() -> str:
    return SAMPLE_DUMP
