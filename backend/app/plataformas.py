"""Catálogo de SISTEMAS/plataformas: el nombre OFICIAL de cada sistema del volcado.

La colección retro vive en carpetas hechas a mano cuyo nombre es un CÓDIGO del
volcado (`ARC N-W!!`, `ARC S3G4-Mega Drive-G3N3S1S`, `ARC 5NK-NE0GE0`…). Ese
código es la identidad del contenido en MEGA (exactamente igual que el nombre
real del fichero ROM en `titles.name`) y por eso `titles.letter` lo conserva,
pero no es lo que un catálogo debe enseñar. Este módulo traduce ese código al
nombre OFICIAL de la plataforma, tomado del catálogo `/v4/platforms` de IGDB
(220 plataformas, consultado en vivo): de ahí salen también `igdb_id`,
`igdb_slug`, `generacion` y `familia` (esta última solo cuando IGDB la define,
p. ej. Nintendo/Sega/PlayStation/Xbox/Atari).

Se resuelve AL VUELO, no en la BD: el mapa es estático y vive en una sola
fuente de verdad (código), de modo que añadir o renombrar una plataforma se
propaga a todo el catálogo al instante, sin migración ni pase de puesta al día
que pueda quedarse obsoleto. Un código que aún no esté en el catálogo NO se
inventa: se publica tal cual con `conocido=False` para que la UI lo pueda avisar.

Tres plataformas del volcado no existen en IGDB (comprobado en vivo): los
sistemas arcade `Sega NAOMI` y `Atomiswave` (IGDB solo tiene la plataforma
`Arcade` genérica) y `ScummVM` (que es el intérprete con el que se juegan las
ROMs, no un sistema). En esos casos se publica el nombre oficial del
hardware/software con `igdb_id=None`; MAME sí se mapea a la plataforma `Arcade`
de IGDB, que es su equivalente real.

Uso:
    from app import plataformas

    plataformas.de_letra("ARC N-W!!").nombre        # "Wii"
    plataformas.de_letra("A").nombre                # "Nintendo Switch"
    plataformas.etiquetas_de("mega-drive")          # ("ARC S3G4-Mega Drive-G3N3S1S",)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import slugify

# Bucket del catálogo de Switch: `letter` es la letra A-Z (`#`, `0`…`9`), no un
# sistema. Se reconoce por su forma para no tener que pasar la colección.
_LETRA_SWITCH_RE = re.compile(r"^#$|^[0-9A-Z]{1,2}$")
_PREFIJO_VOLCADO_RE = re.compile(r"^arc\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Plataforma:
    """Plataforma oficial + las etiquetas del volcado que la alimentan.

    `etiquetas` son los nombres EXACTOS del nivel 1 del volcado (los que acaban
    en `titles.letter`), con sinónimos razonables para que un renombrado de esa
    carpeta en la biblioteca no deje un sistema sin traducir.
    """

    clave: str  # identificador estable (slug) para URLs y claves de UI
    nombre: str  # nombre OFICIAL (catálogo de plataformas de IGDB)
    corto: str  # etiqueta corta para chips y badges (UI densa)
    etiquetas: tuple[str, ...] = ()  # etiquetas del volcado que la alimentan
    igdb_id: int | None = None  # id en `/v4/platforms` (None: IGDB no la tiene)
    igdb_slug: str | None = None
    generacion: int | None = None  # generación de la plataforma según IGDB
    familia: str | None = None  # familia de plataforma (Nintendo, Sega, …)
    conocido: bool = True  # False = código del volcado sin equivalencia oficial


# El catálogo de Switch no tiene códigos: todas sus letras son la misma consola.
SWITCH = Plataforma(
    clave="nintendo-switch",
    nombre="Nintendo Switch",
    corto="Switch",
    igdb_id=130,
    igdb_slug="switch",
    generacion=8,
    familia="Nintendo",
)


# Sistemas/plataformas del volcado retro. El nombre y los datos oficiales vienen
# de IGDB (`/v4/platforms`, consultado en vivo); las etiquetas, del volcado real.
PLATAFORMAS: tuple[Plataforma, ...] = (
    # ── Nintendo ────────────────────────────────────────────────────────────
    Plataforma(
        clave="nintendo-64",
        nombre="Nintendo 64",
        corto="N64",
        etiquetas=("ARC N-64", "ARC N64"),
        igdb_id=4,
        igdb_slug="n64",
        generacion=5,
        familia="Nintendo",
    ),
    Plataforma(
        clave="gamecube",
        nombre="Nintendo GameCube",
        corto="GameCube",
        etiquetas=("ARC N-GC",),
        igdb_id=21,
        igdb_slug="ngc",
        generacion=6,
        familia="Nintendo",
    ),
    Plataforma(
        clave="wii",
        nombre="Wii",
        corto="Wii",
        etiquetas=("ARC N-W!!", "ARC N-WII"),
        igdb_id=5,
        igdb_slug="wii",
        generacion=7,
        familia="Nintendo",
    ),
    Plataforma(
        clave="wii-u",
        nombre="Wii U",
        corto="Wii U",
        etiquetas=("ARC N-W!!U", "ARC N-WIIU"),
        igdb_id=41,
        igdb_slug="wiiu",
        generacion=8,
        familia="Nintendo",
    ),
    Plataforma(
        clave="nes",
        nombre="Nintendo Entertainment System",
        corto="NES",
        etiquetas=("ARC N-NES",),
        igdb_id=18,
        igdb_slug="nes",
        generacion=3,
        familia="Nintendo",
    ),
    Plataforma(
        clave="snes",
        nombre="Super Nintendo Entertainment System",
        corto="SNES",
        etiquetas=("ARC N-SNE5", "ARC N-SNES"),
        igdb_id=19,
        igdb_slug="snes",
        generacion=4,
        familia="Nintendo",
    ),
    Plataforma(
        clave="game-boy",
        nombre="Game Boy",
        corto="GB",
        etiquetas=("ARC N-GB",),
        igdb_id=33,
        igdb_slug="gb",
        generacion=4,
        familia="Nintendo",
    ),
    Plataforma(
        clave="game-boy-color",
        nombre="Game Boy Color",
        corto="GBC",
        etiquetas=("ARC N-GBC",),
        igdb_id=22,
        igdb_slug="gbc",
        generacion=5,
        familia="Nintendo",
    ),
    Plataforma(
        clave="game-boy-advance",
        nombre="Game Boy Advance",
        corto="GBA",
        etiquetas=("ARC N-GBA",),
        igdb_id=24,
        igdb_slug="gba",
        generacion=6,
        familia="Nintendo",
    ),
    Plataforma(
        clave="nintendo-ds",
        nombre="Nintendo DS",
        corto="NDS",
        etiquetas=("ARC N-DS", "ARC NDS"),
        igdb_id=20,
        igdb_slug="nds",
        generacion=7,
        familia="Nintendo",
    ),
    Plataforma(
        clave="nintendo-3ds",
        nombre="Nintendo 3DS",
        corto="3DS",
        etiquetas=("ARC NIN-3DS", "ARC N-3DS"),
        igdb_id=37,
        igdb_slug="3ds",
        generacion=8,
        familia="Nintendo",
    ),
    # ── PlayStation ─────────────────────────────────────────────────────────
    Plataforma(
        clave="playstation",
        nombre="PlayStation",
        corto="PS1",
        etiquetas=("ARC P-S-1", "ARC PS1"),
        igdb_id=7,
        igdb_slug="ps",
        generacion=5,
        familia="PlayStation",
    ),
    Plataforma(
        clave="playstation-2",
        nombre="PlayStation 2",
        corto="PS2",
        etiquetas=("ARC P-S-2", "ARC PS2"),
        igdb_id=8,
        igdb_slug="ps2",
        generacion=6,
        familia="PlayStation",
    ),
    Plataforma(
        clave="playstation-3",
        nombre="PlayStation 3",
        corto="PS3",
        etiquetas=("ARC P-S-3", "ARC PS3"),
        igdb_id=9,
        igdb_slug="ps3",
        generacion=7,
        familia="PlayStation",
    ),
    Plataforma(
        clave="playstation-4",
        nombre="PlayStation 4",
        corto="PS4",
        etiquetas=("ARC P-S-4", "ARC PS4"),
        igdb_id=48,
        igdb_slug="ps4--1",
        generacion=8,
        familia="PlayStation",
    ),
    Plataforma(
        clave="psp",
        nombre="PlayStation Portable",
        corto="PSP",
        etiquetas=("ARC P-S-P", "ARC PSP"),
        igdb_id=38,
        igdb_slug="psp",
        generacion=7,
        familia="PlayStation",
    ),
    # ── Xbox ────────────────────────────────────────────────────────────────
    Plataforma(
        clave="xbox-360",
        nombre="Xbox 360",
        corto="Xbox 360",
        etiquetas=("ARC X-B0X 360", "ARC XBOX 360"),
        igdb_id=12,
        igdb_slug="xbox360",
        generacion=7,
        familia="Xbox",
    ),
    # ── Sega ────────────────────────────────────────────────────────────────
    Plataforma(
        clave="mega-drive",
        nombre="Sega Mega Drive/Genesis",
        corto="Mega Drive",
        etiquetas=(
            "ARC S3G4-Mega Drive-G3N3S1S",
            "ARC S3G4-Genesis",
            "ARC Sega Mega Drive",
        ),
        igdb_id=29,
        igdb_slug="genesis-slash-megadrive",
        generacion=4,
        familia="Sega",
    ),
    Plataforma(
        clave="sega-32x",
        nombre="Sega 32X",
        corto="32X",
        etiquetas=("ARC S3G4-32X",),
        igdb_id=30,
        igdb_slug="sega32",
        generacion=4,
        familia="Sega",
    ),
    Plataforma(
        clave="sega-cd",
        nombre="Sega CD",
        corto="Sega CD",
        etiquetas=("ARC S3G4-Mega-CD", "ARC Sega CD"),
        igdb_id=78,
        igdb_slug="sega-cd",
        generacion=4,
        familia="Sega",
    ),
    Plataforma(
        clave="master-system",
        nombre="Sega Master System/Mark III",
        corto="Master System",
        etiquetas=("ARC S3G4-MSM-III", "ARC S3G4-Master System"),
        igdb_id=64,
        igdb_slug="sms",
        generacion=3,
        familia="Sega",
    ),
    Plataforma(
        clave="game-gear",
        nombre="Sega Game Gear",
        corto="Game Gear",
        etiquetas=("ARC S3G4-Game Gear",),
        igdb_id=35,
        igdb_slug="gamegear",
        generacion=4,
        familia="Sega",
    ),
    Plataforma(
        clave="sg-1000",
        nombre="SG-1000",
        corto="SG-1000",
        etiquetas=("ARC S3G4-SG-1000",),
        igdb_id=84,
        igdb_slug="sg1000",
        generacion=3,
        familia="Sega",
    ),
    Plataforma(
        clave="dreamcast",
        nombre="Dreamcast",
        corto="Dreamcast",
        etiquetas=("ARC S3G4-Dreamcast",),
        igdb_id=23,
        igdb_slug="dc",
        generacion=6,
        familia="Sega",
    ),
    # Hardware arcade de Sega: IGDB no lo publica como plataforma propia (solo
    # tiene la `Arcade` genérica), así que se conserva el nombre oficial real.
    Plataforma(
        clave="naomi",
        nombre="Sega NAOMI",
        corto="NAOMI",
        etiquetas=("ARC S3G4-Naomi", "ARC Naomi"),
    ),
    Plataforma(
        clave="atomiswave",
        nombre="Atomiswave",
        corto="Atomiswave",
        etiquetas=("ARC S3G4-Atomiswave", "ARC Atomiswave"),
    ),
    # ── Arcade (emulación) ──────────────────────────────────────────────────
    Plataforma(
        clave="mame-2003",
        nombre="Arcade (MAME 2003)",
        corto="MAME",
        etiquetas=("ARC Mame2003", "ARC MAME"),
        igdb_id=52,
        igdb_slug="arcade",
    ),
    Plataforma(
        clave="arcade-vertical",
        nombre="Arcade (vertical)",
        corto="Arcade V",
        etiquetas=("ARC Arcade-Vertical-Games",),
        igdb_id=52,
        igdb_slug="arcade",
    ),
    # ── SNK ─────────────────────────────────────────────────────────────────
    Plataforma(
        clave="neo-geo",
        nombre="Neo Geo AES/MVS",
        corto="Neo Geo",
        etiquetas=("ARC 5NK-NE0GE0", "ARC SNK-NE0GE0"),
        igdb_id=80,  # IGDB separa AES (80) y MVS (79): es la misma generación SNK
        igdb_slug="neogeoaes",
        generacion=4,
    ),
    Plataforma(
        clave="neo-geo-cd",
        nombre="Neo Geo CD",
        corto="Neo Geo CD",
        etiquetas=("ARC SNK-NE0GE0-CD",),
        igdb_id=136,
        igdb_slug="neo-geo-cd",
        generacion=4,
    ),
    Plataforma(
        clave="neo-geo-pocket-color",
        nombre="Neo Geo Pocket Color",
        corto="NGPC",
        etiquetas=("ARC 5NK-NE0GE0-Pocket", "ARC Neo Geo Pocket"),
        igdb_id=120,
        igdb_slug="neo-geo-pocket-color",
        generacion=5,
    ),
    # ── Atari ───────────────────────────────────────────────────────────────
    Plataforma(
        clave="atari-2600",
        nombre="Atari 2600",
        corto="Atari 2600",
        etiquetas=("ARC Atari-2600",),
        igdb_id=59,
        igdb_slug="atari2600",
        generacion=2,
        familia="Atari",
    ),
    Plataforma(
        clave="atari-7800",
        nombre="Atari 7800",
        corto="Atari 7800",
        etiquetas=("ARC Atari-7800",),
        igdb_id=60,
        igdb_slug="atari7800",
        generacion=3,
    ),
    Plataforma(
        clave="atari-lynx",
        nombre="Atari Lynx",
        corto="Lynx",
        etiquetas=("ARC Atari-Lynx",),
        igdb_id=61,
        igdb_slug="lynx",
        generacion=4,
    ),
    # ── Microordenadores ────────────────────────────────────────────────────
    Plataforma(
        clave="amstrad-cpc",
        nombre="Amstrad CPC",
        corto="CPC",
        etiquetas=("ARC Amstrad-CPC",),
        igdb_id=25,
        igdb_slug="acpc",
    ),
    Plataforma(
        clave="commodore-64",
        nombre="Commodore C64/128/MAX",
        corto="C64",
        etiquetas=("ARC Commodore-64",),
        igdb_id=15,
        igdb_slug="c64",
    ),
    Plataforma(
        clave="msx",
        nombre="MSX",
        corto="MSX",
        etiquetas=("ARC Microsoft-MSX", "ARC MSX"),
        igdb_id=27,
        igdb_slug="msx",
    ),
    Plataforma(
        clave="sharp-x68000",
        nombre="Sharp X68000",
        corto="X68000",
        etiquetas=("ARC Sharp-X68000",),
        igdb_id=121,
        igdb_slug="sharp-x68000",
    ),
    Plataforma(
        clave="zx-spectrum",
        nombre="ZX Spectrum",
        corto="ZX Spectrum",
        etiquetas=("ARC Sinclair-ZXS", "ARC ZX-Spectrum"),
        igdb_id=26,
        igdb_slug="zxs",
    ),
    # ── Otras consolas ──────────────────────────────────────────────────────
    Plataforma(
        clave="pc-engine",
        nombre="TurboGrafx-16/PC Engine",
        corto="PC Engine",
        etiquetas=("ARC TurboGrafx-16", "ARC PC Engine"),
        igdb_id=86,
        igdb_slug="turbografx16--1",
        generacion=4,
    ),
    Plataforma(
        clave="pc-engine-cd",
        nombre="Turbografx-16/PC Engine CD",
        corto="PC Engine CD",
        etiquetas=("ARC TurboGrafx-CD",),
        igdb_id=150,
        igdb_slug="turbografx-16-slash-pc-engine-cd",
    ),
    Plataforma(
        clave="handheld-electronic-lcd",
        nombre="Handheld Electronic LCD",
        corto="Handheld",
        etiquetas=("ARC Handheld-Electronic-Game",),
        igdb_id=411,
        igdb_slug="handheld",
    ),
    # ScummVM es el intérprete con el que se juegan estas ROMs, no un sistema, y
    # IGDB no lo publica como plataforma: se conserva su nombre propio.
    Plataforma(
        clave="scummvm",
        nombre="ScummVM",
        corto="ScummVM",
        etiquetas=("ARC ScummVM",),
    ),
)


def etiqueta(nombre: str) -> str:
    """Normaliza una etiqueta del volcado (o una clave) para emparejarla.

    Solo se quita el prefijo `ARC ` (marca de la colección) y se colapsan los
    espacios: los códigos del volcado son deliberadamente raros (`N-W!!`,
    `NE0GE0`) y "adivinar" leetspeak crearía equivalencias falsas.
    """
    limpio = _PREFIJO_VOLCADO_RE.sub("", nombre.strip())
    return re.sub(r"\s+", " ", limpio).casefold()


def _indice() -> dict[str, Plataforma]:
    """Etiquetas del volcado y nombres oficiales → plataforma (una sola fuente)."""
    indice: dict[str, Plataforma] = {}
    for p in PLATAFORMAS:
        for texto in (*p.etiquetas, p.nombre):
            clave = etiqueta(texto)
            previo = indice.get(clave)
            if previo is not None and previo is not p:  # error de programación
                raise ValueError(
                    f"etiqueta de plataforma duplicada: {texto!r} ({previo.clave} y {p.clave})"
                )
            indice[clave] = p
    return indice


_INDICE: dict[str, Plataforma] = _indice()
_POR_CLAVE: dict[str, Plataforma] = {p.clave: p for p in PLATAFORMAS}


def desconocida(codigo: str) -> Plataforma:
    """Plataforma de un código del volcado que aún no está en el catálogo.

    No se inventa nada: se publica el código tal cual (sin el prefijo `ARC `, que
    es andamiaje de la colección) y `conocido=False`, para que la UI pueda avisar
    de que ese sistema estrena nombre oficial.
    """
    bruto = codigo.strip() or "—"
    return Plataforma(
        clave=slugify(bruto),
        nombre=bruto,
        corto=_PREFIJO_VOLCADO_RE.sub("", bruto) or bruto,
        conocido=False,
    )


def resolver(codigo: str) -> Plataforma:
    """Plataforma de una etiqueta del volcado (`ARC N-W!!` → Wii)."""
    return _INDICE.get(etiqueta(codigo)) or desconocida(codigo)


def es_letra_switch(letter: str) -> bool:
    """¿El bucket es la letra A-Z del catálogo de Switch (y no un sistema)?"""
    return bool(_LETRA_SWITCH_RE.match(letter.strip().upper()))


def de_letra(letter: str) -> Plataforma:
    """Plataforma que se publica para el bucket de un título.

    En Switch `letter` es la letra del abecedario (todos los juegos son la misma
    consola); en retro es el SISTEMA del volcado, que aquí se traduce a su nombre
    oficial. Un sistema desconocido nunca revienta el catálogo: cae al nombre del
    volcado con `conocido=False`.
    """
    if not letter.strip() or es_letra_switch(letter):
        return SWITCH
    return resolver(letter)


def etiquetas_de(valor: str) -> list[str]:
    """Etiquetas del volcado que alimentan lo que pide el usuario.

    Acepta la clave canónica (`mega-drive`), el nombre oficial
    (`Sega Mega Drive/Genesis`) o la propia etiqueta del volcado, de modo que los
    enlaces nuevos del catálogo pueden ser legibles sin romper los antiguos. Si
    no reconoce el valor lo devuelve tal cual: un filtro por etiqueta suelta (o
    por un sistema que todavía no esté en el catálogo) sigue funcionando.
    """
    p = _POR_CLAVE.get(etiqueta(valor)) or _INDICE.get(etiqueta(valor))
    if p is None or not p.etiquetas:
        return [valor]
    return list(p.etiquetas)
