"""Motor y sesiones SQLAlchemy.

SQLite por defecto (WAL, `check_same_thread=False`); cualquier URL de SQLAlchemy
(v. gr. Postgres) funciona cambiando `ALUCARD_DATABASE_URL`.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Base


def build_engine(database_url: str):
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_prgmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(database_url, pool_pre_ping=True, future=True)


def create_schema(database_url: str) -> None:
    """Crea las tablas si no existen (F0: sin alembic todavía)."""
    Base.metadata.create_all(build_engine(database_url))


def make_session_factory(database_url: str):
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
