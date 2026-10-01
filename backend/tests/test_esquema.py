"""Puesta al día del esquema: `create_schema` añade columnas nuevas sin alembic.

Las bases desplegadas (`alucard.db`, `retro.db`) se crearon antes de que existiera
la identidad canónica de IGDB (`titles.igdb_name`/`igdb_name_norm`/`igdb_year`):
al arrancar cualquier proceso (API, workers, CLI) `migrar_esquema` las añade con
un `ALTER TABLE` idempotente, sin perder filas ni tocar los datos existentes.
"""

from __future__ import annotations

from app.db import build_engine, create_schema, migrar_esquema

_COLUMNAS_CANONICAS = {"igdb_name", "igdb_name_norm", "igdb_year"}


def _base_antigua(url: str) -> None:
    """`titles` tal y como era antes de la identidad canónica (con datos reales)."""
    engine = build_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE titles ("
            "id INTEGER PRIMARY KEY, snapshot_id INTEGER, slug VARCHAR, name TEXT, "
            "name_norm TEXT, letter VARCHAR, igdb_slug VARCHAR, igdb_cover TEXT, "
            "igdb_json TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO titles (snapshot_id, slug, name, name_norm, letter) "
            "VALUES (1, 'after-burner', 'After Burner.zip', 'after burner zip', "
            "'ARC Mame2003')"
        )


def test_create_schema_anade_las_columnas_canonicas_a_una_base_antigua(tmp_path):
    url = f"sqlite:///{tmp_path / 'alucard.db'}"
    _base_antigua(url)

    create_schema(url)  # arranque de la API/worker sobre una BD ya existente

    engine = build_engine(url)
    with engine.connect() as conn:
        columnas = {fila[1] for fila in conn.exec_driver_sql("PRAGMA table_info(titles)")}
        fila = conn.exec_driver_sql(
            "SELECT name, igdb_name, igdb_name_norm, igdb_year FROM titles WHERE id = 1"
        ).one()
    assert columnas >= _COLUMNAS_CANONICAS
    # La fila antigua sigue entera y los campos nuevos entran vacíos (NULL).
    assert tuple(fila) == ("After Burner.zip", None, None, None)


def test_migrar_esquema_es_idempotente(tmp_path):
    url = f"sqlite:///{tmp_path / 'retro.db'}"
    create_schema(url)  # base nueva: ya nace con las columnas
    assert migrar_esquema(build_engine(url)) == []
    assert migrar_esquema(build_engine(url)) == []


def test_migrar_esquema_ignora_tablas_que_no_existen(tmp_path):
    """Sin `titles` todavía, no hay nada que migrar (lo crea `create_all`)."""
    url = f"sqlite:///{tmp_path / 'vacia.db'}"
    engine = build_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE otras (id INTEGER PRIMARY KEY)")
    assert migrar_esquema(engine) == []
