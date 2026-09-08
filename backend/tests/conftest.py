"""Fixtures compartidos: app con BD temporal y volcado de muestra ingerido."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.parser import parse_text

from .sample_dump import SAMPLE_DUMP


def build_app(tmp_path, text: str = SAMPLE_DUMP):
    db = tmp_path / "test.db"
    cfg = Settings(database_url=f"sqlite:///{db}")
    app = create_app(cfg)

    from app.ingest import ingest

    ingest(app.state.engine, parse_text(text), source_kind="dump",
           source_path=":memory-sample:")
    return app


@pytest.fixture()
def client(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_text() -> str:
    return SAMPLE_DUMP
