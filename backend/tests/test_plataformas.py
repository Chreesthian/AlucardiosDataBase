"""Plataformas/sistemas: el nombre OFICIAL de cada bucket del catálogo.

El volcado retro nombra sus sistemas con códigos hechos a mano (`ARC N-W!!`,
`ARC S3G4-Mega Drive-G3N3S1S`, `ARC 5NK-NE0GE0`…) y el catálogo de Switch usa
letras. `app.plataformas` traduce ambas cosas al nombre oficial de la plataforma
(catálogo `/v4/platforms` de IGDB) y la API lo publica junto al bucket, así que
la UI nunca tiene que enseñar el código del volcado.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import plataformas as P

from .conftest import build_app

# Volcado retro mínimo con un sistema que NO está en el catálogo oficial.
DUMP_RETRO_DESCONOCIDO = """\
VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)
======================================================================
Cuenta            : retro@example.com
Fecha de volcado  : 2026-09-30T00:00:00
Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)
Archivos          : 1
Carpetas          : 2
Tamano total      : 100 bytes

======================================================================
SECTOR: INSHARE duenio@example.com:ORTIK 90
======================================================================
Archivos  : 1
Carpetas  : 2
Tamano    : 100 bytes

[ROOT] //from/duenio@example.com:ORTIK 90/
`-- [FOLDER] ARC System-3000/
    `-- [FILE] mystereo.zip  (100 bytes)
"""


def test_catalogo_coherente_y_sin_etiquetas_duplicadas():
    """Cada plataforma es única y sus etiquetas apuntan de vuelta a ella."""
    claves = [p.clave for p in P.PLATAFORMAS]
    nombres = [p.nombre for p in P.PLATAFORMAS]
    assert len(set(claves)) == len(claves)
    assert len(set(nombres)) == len(nombres)

    for p in P.PLATAFORMAS:
        assert p.etiquetas, f"{p.clave} sin etiquetas del volcado"
        for etiqueta in p.etiquetas:
            assert P.resolver(etiqueta) is p
            # La clave también resuelve a su plataforma (filtro por clave en la API).
            assert P.etiquetas_de(p.clave) == list(p.etiquetas)
        assert P.etiquetas_de(p.nombre) == list(p.etiquetas)


def test_los_codigos_del_volcado_se_traducen_a_nombre_oficial():
    """Los códigos más retorcidos del volcado real tienen nombre oficial."""
    esperado = {
        "ARC N-64": "Nintendo 64",
        "ARC N-GC": "Nintendo GameCube",
        "ARC N-W!!": "Wii",
        "ARC N-W!!U": "Wii U",
        "ARC N-SNE5": "Super Nintendo Entertainment System",
        "ARC NIN-3DS": "Nintendo 3DS",
        "ARC P-S-1": "PlayStation",
        "ARC P-S-P": "PlayStation Portable",
        "ARC X-B0X 360": "Xbox 360",
        "ARC S3G4-Mega Drive-G3N3S1S": "Sega Mega Drive/Genesis",
        "ARC S3G4-MSM-III": "Sega Master System/Mark III",
        "ARC 5NK-NE0GE0": "Neo Geo AES/MVS",
        "ARC SNK-NE0GE0-CD": "Neo Geo CD",
        "ARC 5NK-NE0GE0-Pocket": "Neo Geo Pocket Color",
        "ARC Mame2003": "Arcade (MAME 2003)",
        "ARC Atari-2600": "Atari 2600",
        "ARC Commodore-64": "Commodore C64/128/MAX",
        "ARC Sinclair-ZXS": "ZX Spectrum",
        "ARC TurboGrafx-16": "TurboGrafx-16/PC Engine",
        "ARC Handheld-Electronic-Game": "Handheld Electronic LCD",
        "ARC ScummVM": "ScummVM",
    }
    for codigo, oficial in esperado.items():
        p = P.de_letra(codigo)
        assert (p.nombre, p.conocido) == (oficial, True), codigo


def test_los_datos_oficiales_vienen_de_igdb():
    """Id, slug, generación y familia son los que publica IGDB (los verificados)."""
    wii = P.de_letra("ARC N-W!!")
    assert (wii.igdb_id, wii.igdb_slug, wii.generacion, wii.familia) == (5, "wii", 7, "Nintendo")
    genesis = P.de_letra("ARC S3G4-Mega Drive-G3N3S1S")
    assert (genesis.igdb_id, genesis.igdb_slug, genesis.familia) == (
        29,
        "genesis-slash-megadrive",
        "Sega",
    )
    # Sistemas que IGDB no publica como plataforma: nombre oficial, sin id.
    for codigo in ("ARC S3G4-Naomi", "ARC S3G4-Atomiswave", "ARC ScummVM"):
        assert P.de_letra(codigo).igdb_id is None


def test_un_codigo_desconocido_se_publica_tal_cual_y_marcado():
    """Un sistema nuevo del volcado no se inventa: se avisa con `conocido=False`."""
    p = P.de_letra("ARC Sistema-Nuevo-3000")
    assert p.conocido is False
    assert p.nombre == "ARC Sistema-Nuevo-3000"  # el código, sin adornos
    assert p.corto == "Sistema-Nuevo-3000"  # el prefijo ARC es andamiaje
    assert p.clave == "arc-sistema-nuevo-3000"
    assert p.igdb_id is None


def test_las_letras_del_catalogo_de_switch_son_nintendo_switch():
    """En Switch el bucket es la letra: todas son la misma consola."""
    for letra in ("A", "Z", "#", "0", "9", ""):
        assert P.de_letra(letra).clave == "nintendo-switch"
    assert P.SWITCH.nombre == "Nintendo Switch"
    # Un sistema del volcado nunca se confunde con una letra.
    assert not P.es_letra_switch("ARC N-64")
    assert not P.es_letra_switch("ARC S3G4-Mega Drive-G3N3S1S")


def test_etiquetas_de_acepta_clave_nombre_y_codigo():
    """El filtro de la API admite clave, nombre oficial y código del volcado."""
    genesis = P.de_letra("ARC S3G4-Mega Drive-G3N3S1S")
    assert P.etiquetas_de("mega-drive") == list(genesis.etiquetas)
    assert P.etiquetas_de("Sega Mega Drive/Genesis") == list(genesis.etiquetas)
    assert P.etiquetas_de("ARC S3G4-Mega Drive-G3N3S1S") == list(genesis.etiquetas)
    # Lo que no reconoce lo deja pasar tal cual (filtro literal, no se pierde).
    assert P.etiquetas_de("ARC Sistema-Nuevo") == ["ARC Sistema-Nuevo"]


# ── lo que publica la API ────────────────────────────────────
def test_api_switch_publica_la_plataforma(client):
    meta = client.get("/api/meta").json()
    assert [b["plataforma"]["clave"] for b in meta["buckets"]] == ["nintendo-switch"] * 2
    assert {b["plataforma"]["nombre"] for b in meta["buckets"]} == {"Nintendo Switch"}

    item = client.get("/api/titles").json()["items"][0]
    assert item["letter"] == "A"  # la identidad del volcado sigue ahí
    assert item["plataforma"]["igdb_id"] == 130

    detalle = client.get("/api/titles/a-game-one").json()
    assert detalle["plataforma"]["corto"] == "Switch"


def test_api_retro_publica_la_plataforma_oficial(client_retro):
    sistemas = client_retro.get("/api/retro/sistemas").json()
    # Ordenados por el NOMBRE OFICIAL (no por el código del volcado).
    assert [s["plataforma"]["nombre"] for s in sistemas] == [
        "Arcade (MAME 2003)",
        "Neo Geo AES/MVS",
        "Nintendo 64",
    ]
    assert [P.resolver(s["letter"]).nombre for s in sistemas] == [
        "Arcade (MAME 2003)",
        "Neo Geo AES/MVS",
        "Nintendo 64",
    ]

    item = client_retro.get("/api/retro/titles", params={"q": "banjo kazooie"}).json()["items"][0]
    assert item["letter"] == "ARC N-64"
    assert item["plataforma"] == {
        "clave": "nintendo-64",
        "nombre": "Nintendo 64",
        "corto": "N64",
        "igdb_id": 4,
        "igdb_slug": "n64",
        "generacion": 5,
        "familia": "Nintendo",
        "conocido": True,
    }

    detalle = client_retro.get("/api/retro/titles/3wonders-zip").json()
    assert detalle["plataforma"]["nombre"] == "Arcade (MAME 2003)"


def test_api_retro_filtra_por_cualquiera_de_los_tres_nombres(client_retro):
    """`sistema` acepta la clave canónica, el nombre oficial y el código."""
    for valor in ("nintendo-64", "Nintendo 64", "ARC N-64"):
        data = client_retro.get("/api/retro/titles", params={"sistema": valor}).json()
        assert data["total"] == 3, valor
        assert {i["plataforma"]["corto"] for i in data["items"]} == {"N64"}

    mame = client_retro.get("/api/retro/titles", params={"sistema": "mame-2003"}).json()
    assert {i["name"] for i in mame["items"]} == {"3wonders.zip", "aof.zip"}

    # Un sistema que no existe devuelve cero, no el catálogo entero.
    assert (
        client_retro.get("/api/retro/titles", params={"sistema": "no-existe"}).json()["total"] == 0
    )


def test_api_retro_senala_un_sistema_sin_traducir(tmp_path):
    """Un sistema nuevo del volcado se publica con `conocido=False` (la UI avisa)."""
    app = build_app(tmp_path, retro_text=DUMP_RETRO_DESCONOCIDO)
    with TestClient(app) as c:
        sistemas = c.get("/api/retro/sistemas").json()
    assert [s["plataforma"] for s in sistemas] == [
        {
            "clave": "arc-system-3000",
            "nombre": "ARC System-3000",
            "corto": "System-3000",
            "igdb_id": None,
            "igdb_slug": None,
            "generacion": None,
            "familia": None,
            "conocido": False,
        }
    ]
