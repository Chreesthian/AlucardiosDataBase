"""Motor y sesiones SQLAlchemy.

SQLite por defecto (WAL, `check_same_thread=False`); cualquier URL de SQLAlchemy
(v. gr. Postgres) funciona cambiando `ALUCARD_DATABASE_URL`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_prgmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(database_url, pool_pre_ping=True, future=True)


# Columnas añadidas DESPUÉS de la primera versión de cada tabla. `create_all` no
# toca tablas ya existentes, así que las bases desplegadas (alucard.db, retro.db)
# se pondrían al día solas con un `ALTER TABLE … ADD COLUMN` (idempotente) al
# arrancar cualquier proceso (API, workers, CLI). SQLite añade columnas NULL sin
# reescribir la tabla, así que es instantáneo y no pierde datos.
_COLUMNAS_NUEVAS: dict[str, dict[str, str]] = {
    "titles": {
        "igdb_name": "TEXT",
        "igdb_name_norm": "TEXT",
        "igdb_year": "INTEGER",
    },
}


def migrar_esquema(engine: Engine) -> list[str]:
    """Añade las columnas que falten en bases ya existentes. Devuelve las creadas."""
    if engine.dialect.name != "sqlite":  # pragma: no cover - Postgres usa alembic
        return []
    nuevas: list[str] = []
    with engine.begin() as conn:
        for tabla, columnas in _COLUMNAS_NUEVAS.items():
            existentes = {fila[1] for fila in conn.exec_driver_sql(f"PRAGMA table_info({tabla})")}
            if not existentes:  # la tabla no existe todavía: la crea `create_all`
                continue
            for columna, tipo in columnas.items():
                if columna in existentes:
                    continue
                conn.exec_driver_sql(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
                nuevas.append(f"{tabla}.{columna}")
    return nuevas


def create_schema(database_url: str) -> None:
    """Crea las tablas si no existen y pone al día las columnas nuevas (sin alembic)."""
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    migrar_esquema(engine)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
