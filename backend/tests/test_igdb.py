"""Tests del sistema IGDB (paridad con el conector de un proyecto anterior) y del enriquecedor."""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select

from app.enrich import (
    aplicar,
    campos_canonicos,
    limpiar_para_reprocesar,
    listar_trabajo,
    necesita_trabajo,
    rellenar_campos_canonicos,
    run,
    version,
)
from app.igdb import (
    IgdbApiError,
    IgdbConnector,
    JuegoIgdb,
    _aceptable_v3,
    _compactar_letras_espaciadas,
    _eleccion_inequivoca,
    _encaja_core_decorativo,
    _enlaces_desde,
    _idiomas_desde,
    _imagen_igdb,
    _lanzamientos_desde,
    _texto_clasificacion,
    _titulo_busqueda_libre,
    _variantes_para,
    ficha_desde_juego,
    titulo_para_igdb,
    titulo_para_igdb_rom,
)
from app.library import current_snapshot
from app.models import Title

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP


def test_limpieza_titulo():
    # Normalización ligera: se conservan TODAS las palabras del nombre real.
    assert titulo_para_igdb("God of War Ragnarök") == "god of war ragnarok"
    assert titulo_para_igdb("The Legend of Zelda: Echoes of Wisdom") == (
        "legend of zelda echoes of wisdom"
    )
    assert titulo_para_igdb("Red Dead Redemption II") == "red dead redemption 2"
    assert titulo_para_igdb("Pokémon Escarlata") == "pokemon scarlet"  # alias regional
    # REGRESIÓN: nada de "ruido de tienda" — la consola/edición es parte del título.
    assert titulo_para_igdb("1 2 Switch") == "1 2 switch"
    assert titulo_para_igdb("Among Us") == "among us"
    assert titulo_para_igdb("Super Smash Bros Ultimate") == "super smash bros ultimate"
    assert (
        titulo_para_igdb("ACE COMBAT 7 SKIES UNKNOWN DELUXE EDITION")
        == "ace combat 7 skies unknown deluxe edition"
    )
    assert titulo_para_igdb("Alan Wake Remastered") == "alan wake remastered"
    assert titulo_para_igdb("Ace Attorney Investigations Collection") == (
        "ace attorney investigations collection"
    )


def test_limpieza_titulo_rom():
    # Ruido de dump retro: extensión, región/idioma, revisión y marcas.
    assert titulo_para_igdb_rom("Tomb Raider (USA).7z") == "tomb raider"
    assert titulo_para_igdb_rom("Dementium II (Europe) (En,Fr,De,Es,It).zip") == "dementium 2"
    assert titulo_para_igdb_rom("Super Mario 64 (Japan, USA) [!].zip") == "super mario 64"
    assert titulo_para_igdb_rom("Final Fantasy Origins (USA) (Rev 1).7z") == (
        "final fantasy origins"
    )
    # Carpetas-juego (sin extensión) y nombres con guiones también se limpian.
    assert titulo_para_igdb_rom("Banjo-Kazooie (USA)") == "banjo kazooie"
    assert titulo_para_igdb_rom("Aero Fighters 2") == "aero fighters 2"
    # MAME: nombre corto de ROM set, se deja tal cual (IGDB no lo conoce).
    assert titulo_para_igdb_rom("aof.zip") == "aof"
    # Un punto que NO es extensión de ROM no se recorta.
    assert titulo_para_igdb_rom("Sonic 3.5") == "sonic 3 5"
    # Nombre 100% ruido → sin término de búsqueda (se marca miss, sin red).
    assert titulo_para_igdb_rom("(USA) (Rev 1).zip") == ""
    assert titulo_para_igdb_rom("") == ""


def test_imagen_igdb_normalizada():
    url = "//images.igdb.com/igdb/image/upload/t_thumb/co8d9b.jpg"
    assert _imagen_igdb(url) == ("https://images.igdb.com/igdb/image/upload/t_cover_big/co8d9b.jpg")
    assert _imagen_igdb(None) is None


def test_ficha_desde_raw():
    juego = JuegoIgdb.from_raw(
        {
            "name": "Zelda",
            "slug": "zelda",
            "cover": {"url": "//images.igdb.com/igdb/image/upload/t_thumb/x.jpg"},
            "platforms": [{"name": "Nintendo Switch"}],
            "genres": [{"name": "Adventure"}],
        }
    )
    ficha = ficha_desde_juego(juego)
    assert ficha["slug"] == "zelda"
    assert ficha["caratula"].startswith("https://images.igdb.com/")
    assert ficha["plataformas"] == ["Nintendo Switch"]


def _procesar_stub(nombre: str, previo: dict | None):
    """Falso enriquecedor: match completo (v2) solo para Zelda; miss para el resto."""
    if previo and version(previo) >= 2:
        return None  # ya está al día
    if "Zelda" in nombre:
        return {
            "ficha_v": 2,
            "slug": "zelda-eow",
            "caratula": "https://images.igdb.com/c.jpg",
            "nombre_oficial": "The Legend of Zelda: Echoes of Wisdom",
            "descripcion": "Sinopsis de prueba.",
            "plataformas": ["Nintendo Switch"],
            "videos": [{"nombre": "Tráiler", "video_id": "abc123"}],
        }
    return {"ficha_v": 2, "miss": True}


def test_variantes_sin_prefijo_serie():
    v = _variantes_para("aca neogeo metal slug 3")
    assert v[0] == "aca neogeo metal slug 3"
    assert "metal slug 3" in v


def test_titulo_libre_conserva_consola_del_titulo():
    # Regresión 1-2 Switch: "switch" forma parte del nombre real; el término de
    # búsqueda debe conservarlo (si se quita, el match cae en "Langrisser I & II").
    assert titulo_para_igdb("1 2 Switch") == "1 2 switch"
    assert _titulo_busqueda_libre("1 2 Switch") == "1 2 switch"
    assert _titulo_busqueda_libre("The Legend of Zelda (2023)") == ("legend of zelda")


def test_enriquecimiento_v2_marca_ficha_y_no_repite(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    stats = run(engine, procesar=_procesar_stub)
    assert stats["ok"] == 1  # solo "Zelda Echoes of Wisdom"
    assert stats["detalle"] == 1  # ficha completa v2
    assert stats["miss"] == 2  # los dos "A …" sin match
    assert stats["cobertura"] == 1
    assert stats["con_detalle"] == 1

    # El título resuelto tiene carátula y ficha completa; los demás, probados.
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        snap = current_snapshot(session)
        rows = session.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars().all()
        por_nombre = {t.name: t for t in rows}
        zelda = por_nombre["Zelda Echoes of Wisdom"]
        assert zelda.igdb_cover == "https://images.igdb.com/c.jpg"
        assert zelda.igdb_slug == "zelda-eow"
        assert version(zelda.igdb_json) == 2  # type: ignore[arg-type]
        assert "videos" in (zelda.igdb_json or "")
        game_one = por_nombre["A Game One"]
        assert game_one.igdb_cover is None
        assert game_one.igdb_json == '{"ficha_v": 2, "miss": true}'
        # Sin trabajo pendiente tras la pasada (idempotente/reanudable)
        assert listar_trabajo(session, snap.id) == []

    segunda = run(engine, procesar=_procesar_stub)
    assert segunda["total"] == 0  # nada que re-procesar


def test_enriquecimiento_materializa_el_nombre_canonico(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    stats = run(engine, procesar=_procesar_stub)
    assert stats["con_nombre_oficial"] == 1

    from sqlalchemy.orm import Session

    with Session(engine) as session:
        snap = current_snapshot(session)
        filas = {
            t.name: t
            for t in session.execute(select(Title).where(Title.snapshot_id == snap.id)).scalars()
        }
    # El nombre OFICIAL de IGDB queda en columnas propias; el de la carpeta sigue
    # siendo el nombre real del título (`titles.name`).
    zelda = filas["Zelda Echoes of Wisdom"]
    assert zelda.igdb_name == "The Legend of Zelda: Echoes of Wisdom"
    assert zelda.igdb_name_norm == "the legend of zelda echoes of wisdom"
    assert zelda.igdb_year is None  # la ficha de prueba no trae fecha
    assert zelda.name == "Zelda Echoes of Wisdom"
    # Los 'miss' NO tienen identidad oficial colgando.
    assert filas["A Game One"].igdb_name is None
    assert filas["A Game One"].igdb_name_norm is None


def test_campos_canonicos_deriva_nombre_y_anio():
    assert campos_canonicos(None) == (None, None, None)
    assert campos_canonicos({"miss": True, "nombre_oficial": "X"}) == (None, None, None)
    assert campos_canonicos({"ficha_v": 2}) == (None, None, None)
    cargo = Title(slug="s", name="After Burner.zip", name_norm="after burner zip", letter="ARC")
    aplicar(
        cargo,
        {
            "ficha_v": 2,
            "slug": "after-burner-ii",
            "caratula": "c.jpg",
            "nombre_oficial": "  After   Burner II ",
            "fecha_lanzamiento": "1987-11-01",
        },
    )
    assert (cargo.igdb_name, cargo.igdb_name_norm, cargo.igdb_year) == (
        "After Burner II",
        "after burner ii",
        1987,
    )
    assert cargo.igdb_cover == "c.jpg"
    assert cargo.name == "After Burner.zip"  # el fichero real no se toca
    # Un miss limpia la identidad: no queda un nombre colgado de un match muerto.
    aplicar(cargo, {"ficha_v": 2, "miss": True})
    assert (cargo.igdb_name, cargo.igdb_slug, cargo.igdb_year) == (None, None, None)


def test_rellenar_campos_canonicos_sin_red(tmp_path):
    """Pone al día una base enriquecida antes de que existieran las columnas."""
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    run(engine, procesar=_procesar_stub)

    from sqlalchemy import update
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        snap = current_snapshot(session)
        session.execute(
            update(Title)
            .where(Title.snapshot_id == snap.id)
            .values(igdb_name=None, igdb_name_norm=None, igdb_year=None)
        )
        session.commit()

    res = rellenar_campos_canonicos(engine)
    assert res["filas"] == 3
    assert res["canonicos"] == 1  # solo el título con ficha v2
    assert rellenar_campos_canonicos(engine)["canonicos"] == 0  # idempotente

    with Session(engine) as session:
        zelda = session.execute(
            select(Title).where(Title.name == "Zelda Echoes of Wisdom")
        ).scalar_one()
        assert zelda.igdb_name == "The Legend of Zelda: Echoes of Wisdom"

    # Limpiar para re-resolver suelta también la identidad materializada.
    assert limpiar_para_reprocesar(engine, "Zelda") == 1
    with Session(engine) as session:
        zelda = session.execute(
            select(Title).where(Title.name == "Zelda Echoes of Wisdom")
        ).scalar_one()
        assert zelda.igdb_name is None and zelda.igdb_json is None


def test_necesita_trabajo_segun_version():
    assert necesita_trabajo(None) is True
    assert necesita_trabajo({"slug": "x"}) is True  # v1 básica → ficha
    assert necesita_trabajo({"miss": True}) is True  # miss antiguo
    assert necesita_trabajo({"ficha_v": 2, "slug": "x"}) is False
    assert necesita_trabajo({"ficha_v": 2, "miss": True}) is False


# ── Matcher v3 (lógica pura, sin red) ───────────────────────────────────────


def test_v3_compacta_letras_espaciadas():
    assert _compactar_letras_espaciadas("s n i p e r hunter scope") == ("sniper hunter scope")
    assert (
        _compactar_letras_espaciadas("c a r d s  rpg the misty battlefield")
        == "cards rpg the misty battlefield"
    )
    # Palabras reales de una letra no se mezclan con ruido: "box boy" intacto.
    assert _compactar_letras_espaciadas("box boy") == "box boy"
    assert _compactar_letras_espaciadas("a b c") == "abc"  # acrónimo espaciado


def test_v3_puerta_recupera_y_rechaza():
    # Recupera: números de versión al final, palabras pegadas, geminadas.
    assert _aceptable_v3("blasphemous 1", "Blasphemous")
    assert _aceptable_v3("boxboy boxgirl", "Box Boy! + Box Girl!")
    assert _aceptable_v3("bubbles bubbles ocean", "Bubble Bubble Ocean")
    # Rechaza candidatos parecidos pero que NO son el mismo juego.
    assert not _aceptable_v3("the last dead end", "The Last Stand: Dead Zone")
    assert not _aceptable_v3(
        "before the night",
        "Nights of Azure 2: Bride of the New Moon - Side Story",
    )
    # Regresión de la puerta estricta: 2 palabras compartidas NO bastan.
    assert not _aceptable_v3("soccer tactics glory", "J.League Tactics Soccer")
    assert not _aceptable_v3("doom 1993", "Doom II")


def test_v3_core_decorativo_exacto():
    # '… Nintendo Switch Edition' al final → núcleo exacto 'Beyond Hanwell'.
    assert _encaja_core_decorativo("beyond hanwell nintendo switch edition", "Beyond Hanwell")
    # Números NO se consideran decorativos: 'Pikmin 4' ≠ 'Pikmin'.
    assert not _encaja_core_decorativo("pikmin 4", "Pikmin")
    # Núcleo de una sola palabra no aplica (evita falsos positivos).
    assert not _encaja_core_decorativo("blasphemous", "Blasphemous")


def test_v3_constructores_ficha_ampliada():
    # Lanzamientos por plataforma, ordenados y con región humana.
    lanz = _lanzamientos_desde(
        [
            {
                "platform": {"name": "Nintendo Switch"},
                "date": 1747526400,
                "human": "May 18, 2025",
                "region": 8,
            },
            {"platform": {"name": "PC"}, "date": 1717000000, "human": "May 30, 2024"},
            {
                "platform": {"name": "Nintendo Switch 2"},
                "date": 1748880000,
                "human": "Jun 5, 2025",
                "region": 1,
            },
        ]
    )
    assert lanz[0]["plataforma"] == "PC"
    assert lanz[0]["fecha"] == "2024-05-29"
    assert any(
        x["plataforma"] == "Nintendo Switch"
        and x["region"] == "Mundial"
        and x["humano"] == "May 18, 2025"
        for x in lanz
    )
    assert lanz[-1]["plataforma"] == "Nintendo Switch 2"
    assert lanz[-1]["region"] == "Europa"

    # Enlaces: websites con categoría conocida + tiendas externas por dominio.
    enlaces = _enlaces_desde(
        [{"category": 1, "url": "https://www.example.com/"}],
        [
            {"url": "https://store.steampowered.com/app/2993780"},
            {"url": "https://www.xbox.com/en-us/games/x"},
        ],
    )
    etiquetas = {e["etiqueta"] for e in enlaces}
    assert "Web oficial" in etiquetas
    assert "Steam" in etiquetas
    assert "Xbox" in etiquetas

    # Idiomas únicos.
    idiomas = _idiomas_desde(
        [
            {"language": {"name": "English", "locale": "en"}},
            {"language": {"name": "English", "locale": "en-US"}},
            {"language": {"name": "Spanish (Spain)", "locale": "es-ES"}},
        ]
    )
    assert idiomas == ["English", "Spanish (Spain)"]

    # Clasificaciones.
    assert _texto_clasificacion({"organization": 2, "rating_category": 9}) == "PEGI 7"
    assert _texto_clasificacion({"organization": 1, "rating_category": 3}) == "ESRB E"
    assert _texto_clasificacion({"organization": 3}) == "CERO"


# ── Coste de red: salida temprana del matcher y concurrencia del enriquecedor ──


class _ConnectorFalso(IgdbConnector):
    """Conector sin red: candidatos por término y contador de búsquedas."""

    def __init__(self, respuestas: dict[str, list[JuegoIgdb] | Exception]) -> None:
        self.respuestas = respuestas
        self.consultas: list[str] = []

    def buscar_juego(self, termino: str, *, limite: int = 5) -> list[JuegoIgdb]:
        self.consultas.append(termino)
        respuesta = self.respuestas.get(termino)
        if isinstance(respuesta, Exception):
            raise respuesta
        return list(respuesta or [])


class _ConnectorCaido(IgdbConnector):
    """Conector donde TODAS las búsquedas fallan (429/red/timeout)."""

    def buscar_juego(self, termino: str, *, limite: int = 5) -> list[JuegoIgdb]:
        raise IgdbApiError(429, "rate limit")


def _juego(name: str, slug: str) -> JuegoIgdb:
    return JuegoIgdb(name=name, slug=slug)


def test_eleccion_inequivoca_solo_corta_con_identidad_o_nucleo():
    # Identidad exacta (IGDB escribe ':' y mayúsculas) → corte seguro.
    exacto = _juego("Zelda: Echoes of Wisdom", "zelda-eow")
    assert _eleccion_inequivoca("zelda echoes of wisdom", [exacto]) is exacto
    # Núcleo decorativo exacto (regla 1) → corte seguro.
    core = _juego("Beyond Hanwell", "beyond-hanwell")
    assert _eleccion_inequivoca("beyond hanwell nintendo switch edition", [core]) is core
    # Parecido aceptable pero NO identidad: lo resuelve la regla 2 al final con
    # TODOS los candidatos, así que aquí no se corta (calidad intacta).
    assert _eleccion_inequivoca("blasphemous 1", [_juego("Blasphemous", "blasphemous")]) is None
    # La puerta v2 (`_es_confiable`) NO basta: v3 rechaza este caso a propósito.
    assert (
        _eleccion_inequivoca(
            "aero fighters 2 sonic wings 2", [_juego("Aero Fighters 2", "aero-fighters-2")]
        )
        is None
    )


def test_v3_salida_temprana_ahorra_busquedas():
    conn = _ConnectorFalso({"tomb raider": [_juego("Tomb Raider", "tomb-raider")]})
    juego = conn.mejor_juego_v3("tomb raider", nombre="Tomb Raider (USA).7z")
    assert juego is not None and juego.slug == "tomb-raider"
    # El término limpio va primero y la identidad exacta corta: 1 sola búsqueda
    # (antes se probaban hasta 7 variantes antes de decidir).
    assert conn.consultas == ["tomb raider"]


def test_v3_sin_identidad_recorre_variantes_y_recupera():
    conn = _ConnectorFalso({"blasphemous 1": [_juego("Blasphemous", "blasphemous")]})
    juego = conn.mejor_juego_v3("blasphemous 1")
    assert juego is not None and juego.slug == "blasphemous"  # recuperación intacta
    assert conn.consultas == ["blasphemous 1", "blasphemous"]  # probó el núcleo


def test_v3_propaga_error_si_fallan_todas_las_busquedas():
    with pytest.raises(IgdbApiError):
        _ConnectorCaido().mejor_juego_v3("tomb raider", nombre="Tomb Raider (USA).7z")


def test_run_concurrente_paraleliza_la_red(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine
    hilos: set[str] = set()
    cerrojo = threading.Lock()

    def stub(nombre: str, previo: dict | None):
        with cerrojo:
            hilos.add(threading.current_thread().name)
        time.sleep(0.05)  # sin paralelismo no se solaparían
        return _procesar_stub(nombre, previo)

    stats = run(engine, procesar=stub, concurrencia=4)
    assert stats["ok"] == 1 and stats["detalle"] == 1 and stats["miss"] == 2
    assert stats["cobertura"] == 1 and stats["con_detalle"] == 1
    assert len(hilos) >= 2  # la red sí se paralelizó
    assert stats["por_min"] > 0 and stats["segundos"] >= 0


def test_run_concurrencia_uno_no_cambia_resultados(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    stats = run(app.state.engine, procesar=_procesar_stub, concurrencia=1)
    assert stats["ok"] == 1 and stats["detalle"] == 1 and stats["miss"] == 2
    assert stats["cobertura"] == 1
