"""Colección RETRO (ROMs): catálogo APARTE del de Switch.

Cubre lo que hace distinta a esta colección (`app.ingest`): sistemas en el nivel 1,
juegos que son un ARCHIVO suelto (MAME/Atari), juegos agrupados en carpetas-letra
(`B/`, `#/`), títulos con variante (`B-ASE`), y el aislamiento total respecto al
catálogo de Switch (BD y endpoints distintos).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enrich import run
from app.igdb import JuegoIgdb
from app.ingest import COLECCION_RETRO
from app.library import current_snapshot
from app.models import Node, Title
from app.normalize import slugify
from app.sync import refresh_text

from .conftest import build_app, build_app_retro
from .sample_dump_retro import SAMPLE_DUMP_RETRO


def _titulos(engine) -> list[Title]:
    with Session(engine) as s:
        snap = current_snapshot(s)
        return list(
            s.execute(
                select(Title).where(Title.snapshot_id == snap.id).order_by(Title.name)
            ).scalars()
        )


def test_ingesta_retro_sistemas_juegos_y_roles(tmp_path):
    app = build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)
    engine = app.state.engine_retro

    with Session(engine) as s:
        snap = current_snapshot(s)
        titulos = list(s.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars())
        nodos = list(s.execute(select(Node).where(Node.snapshot_id == snap.id)).scalars())

    # 3 sistemas (bucket) y 7 juegos: 5 archivos sueltos + 2 carpetas-juego.
    sistemas = sorted({t.letter for t in titulos})
    assert sistemas == ["ARC 5NK-NE0GE0", "ARC Mame2003", "ARC N-64"]
    assert len(titulos) == 7

    # La carpeta-letra (`#`, `B`) NO es un juego: es contenedor (rol `group`).
    assert not any(t.name in {"#", "B", "A"} for t in titulos)
    roles = {}
    for n in nodos:
        roles.setdefault(n.role, []).append(n)
    assert {n.name for n in roles["group"]} == {"#", "B"}
    assert len(roles["bucket"]) == 3
    assert len(roles["version"]) == 1  # B-ASE de "Aero Fighters 2"

    # Un juego-archivo (MAME) es un título de 1 archivo con su extensión.
    mangas = {t.name: t for t in titulos}
    tres = mangas["3wonders.zip"]
    assert tres.file_count == 1
    assert tres.folder_count == 0
    assert tres.letter == "ARC Mame2003"
    assert tres.ext_json == '{"zip": 1}'

    # Un juego-carpeta con variante B-ASE conserva base_count y su sistema.
    aero = mangas["Aero Fighters 2"]
    assert aero.base_count == 1
    assert aero.file_count == 1
    assert aero.letter == "ARC 5NK-NE0GE0"

    # El nodo del juego-archivo lleva rol `title` (no queda vacío).
    assert next(n for n in nodos if n.name == "3wonders.zip").role == "title"


def test_sync_retro_incremental_y_estable(tmp_path):
    app = build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)
    engine = app.state.engine_retro

    # Segundo escaneo del MISMO volcado: nada cambia.
    stats = refresh_text(engine, SAMPLE_DUMP_RETRO, coleccion=COLECCION_RETRO)
    assert stats["added_files"] == 0 and stats["removed_files"] == 0
    assert len(_titulos(engine)) == 7

    # Un juego nuevo dentro de un sistema existente → un título más.
    nuevo = SAMPLE_DUMP_RETRO.replace(
        "|   `-- [FILE] aof.zip  (200 bytes)",
        "|   |-- [FILE] aof.zip  (200 bytes)\n" "|   `-- [FILE] mslug.zip  (900 bytes)",
    )
    stats = refresh_text(engine, nuevo, coleccion=COLECCION_RETRO)
    assert stats["added_files"] == 1
    titulos = {t.name: t for t in _titulos(engine)}
    assert "mslug.zip" in titulos
    assert titulos["mslug.zip"].letter == "ARC Mame2003"
    assert len(titulos) == 8


def test_retro_y_switch_no_se_contaminan(client_retro):
    """Cada colección responde por su API y no ve los datos de la otra."""
    switch = client_retro.get("/api/meta").json()
    retro = client_retro.get("/api/retro/meta").json()

    # Switch: los 3 juegos del volcado de muestra; retro: los 7 del suyo.
    assert switch["titles"] == 3
    assert retro["titles"] == 7
    assert {b["letter"] for b in retro["buckets"]} == {
        "ARC 5NK-NE0GE0",
        "ARC Mame2003",
        "ARC N-64",
    }
    assert [b["letter"] for b in switch["buckets"]] == ["A", "Z"]

    # Un juego de ROMs no existe en el catálogo de Switch (y al revés).
    assert client_retro.get("/api/titles/3wonders-zip").status_code == 404
    assert client_retro.get("/api/retro/titles/zoo-tycoon-plus").status_code == 404
    assert client_retro.get("/api/titles/a-game-one").status_code == 200
    assert client_retro.get("/api/retro/titles/3wonders-zip").status_code == 200


def test_retro_detalle_archivo_suelto_y_filtro_por_sistema(client_retro):
    detalle = client_retro.get("/api/retro/titles/3wonders-zip").json()
    assert detalle["letter"] == "ARC Mame2003"
    assert detalle["versions"] == []
    assert [f["name"] for f in detalle["remaining_files"]] == ["3wonders.zip"]
    assert detalle["formats"] == ["ZIP"]
    assert detalle["ficha"] is None  # sin IGDB en esta colección

    aero = client_retro.get("/api/retro/titles/aero-fighters-2").json()
    assert [v["name"] for v in aero["versions"]] == ["B-ASE"]
    assert aero["versions"][0]["label"] == "base"

    listado = client_retro.get("/api/retro/titles", params={"sistema": "ARC Mame2003"}).json()
    assert listado["total"] == 2
    assert {i["name"] for i in listado["items"]} == {"3wonders.zip", "aof.zip"}


def test_retro_sin_catalogo_avisa_y_devuelve_404(client):
    """Sin volcado retro la sección está vacía: la UI debe poder avisarlo."""
    assert client.get("/api/retro/meta").json()["titles"] == 0
    assert client.get("/api/retro/titles").status_code == 404

    estado = client.get("/api/retro/status").json()
    assert estado["disponible"] is False
    assert estado["volcado_existe"] is False
    assert estado["aviso"] and "volcado-retro" in estado["aviso"]


def test_retro_status_con_catalogo(client_retro):
    estado = client_retro.get("/api/retro/status").json()
    assert estado["disponible"] is True
    assert estado["juegos"] == 7
    assert estado["sistemas"] == 3
    # El volcado temporal del test no existe todavía: hay aviso de congelación.
    assert estado["volcado_existe"] is False
    assert estado["aviso"]

    # Con un volcado al día el aviso desaparece y se publica su fuente (in-share),
    # que es la identidad estable de la colección entre rotaciones de cuenta.
    dump = client_retro.app.state.settings.resolved_retro_dump
    dump.write_text(
        SAMPLE_DUMP_RETRO.replace(
            "2026-09-30T00:00:00", datetime.now(UTC).isoformat(timespec="seconds")
        ),
        encoding="utf-8",
    )
    estado = client_retro.get("/api/retro/status").json()
    assert estado["volcado_existe"] is True
    assert estado["volcado_obsoleto"] is False
    assert estado["volcado_fuente"] == "INSHARE duenio@example.com:ORTIK 90"
    assert estado["aviso"] is None


def test_retro_dump_endpoint_escanea_solo_su_bd(client_retro):
    """`POST /api/retro/dump` aplica el diff en la BD retro, nunca en la de Switch."""
    dump = client_retro.app.state.settings.resolved_retro_dump
    dump.write_text(SAMPLE_DUMP_RETRO, encoding="utf-8")

    r = client_retro.post("/api/retro/dump", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client_retro.get("/api/retro/meta").json()["titles"] == 7
    assert client_retro.get("/api/meta").json()["titles"] == 3  # intacto

    # Un volcado ausente responde 404 (el host avisa y el worker reintenta).
    dump.unlink()
    assert client_retro.post("/api/retro/dump", json={}).status_code == 404


# ── Enriquecimiento IGDB de la colección retro ───────────────────────────────
# Las ROMs llegan con ruido de dump en el nombre (`Tomb Raider (USA).7z`) y su
# enriquecimiento lo lleva SU PROPIO worker (`backend-retro-enrich` →
# `app.enrich --coleccion retro`). Aquí se comprueba, SIN red, que el nombre se
# limpia antes de buscar en IGDB, que la ficha se guarda en SU BD y que un
# re-escaneo del volcado NO la borra.


class _ConnectorFalso:
    """Conector IGDB de mentira: solo 'conoce' los términos de `catalogo`."""

    def __init__(self, catalogo: dict[str, tuple[str, str]]) -> None:
        self.catalogo = catalogo
        self.consultados: list[str] = []

    def configurado(self) -> bool:
        return True

    def mejor_juego_v3(self, termino: str, *, nombre: str | None = None) -> JuegoIgdb | None:
        self.consultados.append(termino)
        slug = self.catalogo.get(termino)
        if slug is None:
            return None
        return JuegoIgdb.from_raw({"name": termino, "slug": slug[0]})

    def ficha_detallada(self, slug: str) -> dict | None:
        for _, (encontrado, nombre) in self.catalogo.items():
            if encontrado == slug:
                return {
                    "ficha_v": 2,
                    "slug": slug,
                    "nombre_oficial": nombre,
                    "caratula": "https://images.igdb.com/igdb/image/upload/t_cover_big/x.jpg",
                }
        return None

    def close(self) -> None:
        pass


def _ficha_v2(nombre: str, previo: dict | None) -> dict | None:
    """Enriquecedor de mentira: ficha COMPLETA para todo (sin red)."""
    if previo and not previo.get("miss"):
        return None
    return {
        "ficha_v": 2,
        "slug": slugify(nombre),
        "nombre_oficial": nombre,
        "caratula": "https://images.igdb.com/igdb/image/upload/t_cover_big/x.jpg",
    }


def test_enriquecimiento_retro_limpia_el_nombre_de_rom(tmp_path):
    app = build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)
    engine = app.state.engine_retro
    falso = _ConnectorFalso(
        {
            "banjo kazooie": ("banjo-kazooie", "Banjo-Kazooie"),
            "1080 snowboarding": ("1080-snowboarding", "1080° Snowboarding"),
        }
    )

    stats = run(engine, connector=falso, coleccion=COLECCION_RETRO)

    # A IGDB le llega el título LIMPIO: sin región, sin extensión, sin fichero.
    assert "banjo kazooie" in falso.consultados
    assert "1080 snowboarding" in falso.consultados
    assert not [t for t in falso.consultados if "usa" in t or "zip" in t]
    # Dos juegos de la muestra encuentran ficha completa; el MAME queda como miss.
    assert stats["detalle"] == 2
    assert stats["cobertura"] == 2

    with Session(engine) as s:
        snap = current_snapshot(s)
        filas = {
            t.name: t
            for t in s.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars()
        }
    assert filas["Banjo Kazooie"].igdb_slug == "banjo-kazooie"
    assert filas["Banjo Kazooie"].igdb_cover is not None
    assert filas["3wonders.zip"].igdb_cover is None


def test_sync_retro_no_borra_la_ficha_igdb(tmp_path):
    app = build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)
    engine = app.state.engine_retro
    run(engine, procesar=_ficha_v2)

    # Re-escaneo del MISMO volcado: los títulos que persisten conservan su ficha.
    refresh_text(engine, SAMPLE_DUMP_RETRO, coleccion=COLECCION_RETRO)

    with Session(engine) as s:
        snap = current_snapshot(s)
        filas = list(s.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars())
    assert filas
    assert all(t.igdb_cover for t in filas)
    assert all(t.igdb_slug for t in filas)


def test_retro_status_publica_el_progreso_igdb(tmp_path):
    app = build_app_retro(tmp_path)
    run(app.state.engine_retro, procesar=_ficha_v2)

    with TestClient(app) as c:
        estado = c.get("/api/retro/status").json()
    assert estado["juegos"] == 7
    assert estado["caratulas"] == 7
    assert estado["enriquecidos"] == 7
    assert estado["pendientes_enrich"] == 0
    assert estado["sin_match"] == 0
    # Todas las fichas de prueba traen `nombre_oficial`: el progreso se publica.
    assert estado["con_nombre_oficial"] == 7


def test_api_retro_cataloga_por_el_nombre_oficial(tmp_path):
    """El catálogo se lee por el NOMBRE OFICIAL de IGDB, no por el fichero ROM."""
    app = build_app(tmp_path, retro_text=SAMPLE_DUMP_RETRO)
    engine = app.state.engine_retro
    # Oficiales de mentira, sin red: un fichero MAME (`3wonders.zip`) y un juego
    # de carpeta (`Banjo Kazooie`).
    oficiales = {
        "3wonders.zip": ("three-wonders", "Three Wonders"),
        "Banjo Kazooie": ("banjo-kazooie", "Banjo-Kazooie"),
    }

    def procesar(nombre: str, previo: dict | None) -> dict | None:
        if previo and not previo.get("miss"):
            return None
        par = oficiales.get(nombre)
        if par is None:
            return {"ficha_v": 2, "miss": True}
        slug, oficial = par
        return {
            "ficha_v": 2,
            "slug": slug,
            "nombre_oficial": oficial,
            "caratula": "https://images.igdb.com/igdb/image/upload/t_cover_big/x.jpg",
            "fecha_lanzamiento": "1991-06-23",
        }

    run(engine, procesar=procesar, coleccion=COLECCION_RETRO)

    with TestClient(app) as c:
        # Se encuentra la ROM por su nombre OFICIAL ("Three Wonders" no aparece
        # en el nombre del fichero `3wonders.zip`).
        por_oficial = c.get("/api/retro/titles", params={"q": "Three Wonders"}).json()
        assert [i["name"] for i in por_oficial["items"]] == ["3wonders.zip"]
        assert por_oficial["items"][0]["igdb_name"] == "Three Wonders"
        # Y sigue encontrándose por el nombre real del fichero.
        por_fichero = c.get("/api/retro/titles", params={"q": "aof"}).json()
        assert [i["name"] for i in por_fichero["items"]] == ["aof.zip"]

        # Orden por defecto = nombre OFICIAL; `sort=name` = fichero/carpeta real.
        canonico = [
            i["name"] for i in c.get("/api/retro/titles", params={"limit": 100}).json()["items"]
        ]
        fichero = [
            i["name"]
            for i in c.get("/api/retro/titles", params={"limit": 100, "sort": "name"}).json()[
                "items"
            ]
        ]
        assert canonico == [
            "1080 Snowboarding",
            "Aero Fighters 2",
            "alpham2.zip",
            "aof.zip",
            "Banjo Tooie",
            # `normalize` conserva el guion, así que el nombre oficial
            # "Banjo-Kazooie" ordena después de "Banjo Tooie" (mismo criterio
            # que el resto del catálogo).
            "Banjo Kazooie",
            "3wonders.zip",  # se ordena por "Three Wonders"
        ]
        assert fichero == [
            "1080 Snowboarding",
            "3wonders.zip",
            "Aero Fighters 2",
            "alpham2.zip",
            "aof.zip",
            "Banjo Kazooie",
            "Banjo Tooie",
        ]

        # `sort=year`: por época (los que no tienen año, al final).
        por_anio = c.get("/api/retro/titles", params={"limit": 100, "sort": "year"}).json()
        anios = [i["igdb_year"] for i in por_anio["items"]]
        assert set(anios[:2]) == {1991}
        assert all(a is None for a in anios[2:])

        # Ficha: nombre oficial y año, con el fichero ROM intacto.
        slug = por_oficial["items"][0]["slug"]
        detalle = c.get(f"/api/retro/titles/{slug}").json()
        assert detalle["name"] == "3wonders.zip"
        assert detalle["igdb_name"] == "Three Wonders"
        assert detalle["igdb_year"] == 1991
        assert detalle["ficha"]["nombre_oficial"] == "Three Wonders"

        # Progreso del enriquecimiento: cuántos títulos ya tienen nombre oficial.
        assert c.get("/api/retro/status").json()["con_nombre_oficial"] == 2
