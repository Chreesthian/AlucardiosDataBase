"""Tests del sistema IGDB (paridad con el conector de un proyecto anterior) y del enriquecedor."""

from __future__ import annotations

from sqlalchemy import select

from app.enrich import (
    aplicar,
    listar_trabajo,
    necesita_trabajo,
    procesar_con_connector,
    run,
    version,
)
from app.igdb import (
    JuegoIgdb,
    _aceptable_v3,
    _compactar_letras_espaciadas,
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
    assert titulo_para_igdb(
        "ACE COMBAT 7 SKIES UNKNOWN DELUXE EDITION"
    ) == "ace combat 7 skies unknown deluxe edition"
    assert titulo_para_igdb("Alan Wake Remastered") == "alan wake remastered"
    assert titulo_para_igdb("Ace Attorney Investigations Collection") == (
        "ace attorney investigations collection"
    )


def test_imagen_igdb_normalizada():
    url = "//images.igdb.com/igdb/image/upload/t_thumb/co8d9b.jpg"
    assert _imagen_igdb(url) == (
        "https://images.igdb.com/igdb/image/upload/t_cover_big/co8d9b.jpg"
    )
    assert _imagen_igdb(None) is None


def test_ficha_desde_raw():
    juego = JuegoIgdb.from_raw({
        "name": "Zelda", "slug": "zelda",
        "cover": {"url": "//images.igdb.com/igdb/image/upload/t_thumb/x.jpg"},
        "platforms": [{"name": "Nintendo Switch"}], "genres": [{"name": "Adventure"}],
    })
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
    assert _titulo_busqueda_libre("The Legend of Zelda (2023)") == (
        "legend of zelda"
    )


def test_enriquecimiento_v2_marca_ficha_y_no_repite(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    engine = app.state.engine

    stats = run(engine, procesar=_procesar_stub)
    assert stats["ok"] == 1          # solo "Zelda Echoes of Wisdom"
    assert stats["detalle"] == 1     # ficha completa v2
    assert stats["miss"] == 2        # los dos "A …" sin match
    assert stats["cobertura"] == 1
    assert stats["con_detalle"] == 1

    # El título resuelto tiene carátula y ficha completa; los demás, probados.
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        snap = current_snapshot(session)
        rows = session.execute(
            select(Title).where(Title.snapshot_id == snap.id)
        ).scalars().all()
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


def test_necesita_trabajo_segun_version():
    assert necesita_trabajo(None) is True
    assert necesita_trabajo({"slug": "x"}) is True          # v1 básica → ficha
    assert necesita_trabajo({"miss": True}) is True         # miss antiguo
    assert necesita_trabajo({"ficha_v": 2, "slug": "x"}) is False
    assert necesita_trabajo({"ficha_v": 2, "miss": True}) is False


# ── Matcher v3 (lógica pura, sin red) ───────────────────────────────────────

def test_v3_compacta_letras_espaciadas():
    assert _compactar_letras_espaciadas("s n i p e r hunter scope") == (
        "sniper hunter scope"
    )
    assert _compactar_letras_espaciadas(
        "c a r d s  rpg the misty battlefield"
    ) == "cards rpg the misty battlefield"
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
    assert _encaja_core_decorativo(
        "beyond hanwell nintendo switch edition", "Beyond Hanwell"
    )
    # Números NO se consideran decorativos: 'Pikmin 4' ≠ 'Pikmin'.
    assert not _encaja_core_decorativo("pikmin 4", "Pikmin")
    # Núcleo de una sola palabra no aplica (evita falsos positivos).
    assert not _encaja_core_decorativo("blasphemous", "Blasphemous")


def test_v3_constructores_ficha_ampliada():
    # Lanzamientos por plataforma, ordenados y con región humana.
    lanz = _lanzamientos_desde([
        {"platform": {"name": "Nintendo Switch"}, "date": 1747526400,
         "human": "May 18, 2025", "region": 8},
        {"platform": {"name": "PC"}, "date": 1717000000, "human": "May 30, 2024"},
        {"platform": {"name": "Nintendo Switch 2"}, "date": 1748880000,
         "human": "Jun 5, 2025", "region": 1},
    ])
    assert lanz[0]["plataforma"] == "PC"
    assert lanz[0]["fecha"] == "2024-05-29"
    assert any(l["plataforma"] == "Nintendo Switch" and l["region"] == "Mundial"
               and l["humano"] == "May 18, 2025" for l in lanz)
    assert lanz[-1]["plataforma"] == "Nintendo Switch 2"
    assert lanz[-1]["region"] == "Europa"

    # Enlaces: websites con categoría conocida + tiendas externas por dominio.
    enlaces = _enlaces_desde(
        [{"category": 1, "url": "https://www.example.com/"}],
        [{"url": "https://store.steampowered.com/app/2993780"},
         {"url": "https://www.xbox.com/en-us/games/x"}],
    )
    etiquetas = {e["etiqueta"] for e in enlaces}
    assert "Web oficial" in etiquetas
    assert "Steam" in etiquetas
    assert "Xbox" in etiquetas

    # Idiomas únicos.
    idiomas = _idiomas_desde([
        {"language": {"name": "English", "locale": "en"}},
        {"language": {"name": "English", "locale": "en-US"}},
        {"language": {"name": "Spanish (Spain)", "locale": "es-ES"}},
    ])
    assert idiomas == ["English", "Spanish (Spain)"]

    # Clasificaciones.
    assert _texto_clasificacion({"organization": 2, "rating_category": 9}) == "PEGI 7"
    assert _texto_clasificacion({"organization": 1, "rating_category": 3}) == "ESRB E"
    assert _texto_clasificacion({"organization": 3}) == "CERO"
