"""Conector de IGDB (API v4) — metadatos oficiales de juegos.

Copia del sistema de un-conector-anterior (src/gamechecker/connectors/igdb.py):
misma autenticación OAuth client_credentials, mismo rate-limit (0.3 s),
misma limpieza de títulos (`titulo_para_igdb`) y mismo criterio de match
(`mejor_juego_con_reintento`) que evita fichas incorrectas. De aquí salen la
carátula (t_cover_big) y la ficha que se guarda en `titles.igdb_*`.

Autenticación (client_credentials):
    POST https://id.twitch.tv/oauth2/token → access_token (Bearer + Client-ID).

Consultas en lenguaje **Apicalypse** (cuerpo del POST):
    fields name,slug,summary,…; search "zelda"; limit 5;

Es una fuente **opcional**: sin credenciales, `configurado()` devuelve False y
el enriquecimiento se omite sin romper la app.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings, get_settings

# Enums de clasificación por edad (IGDB v4): organization 2=PEGI, 1=ESRB.
PEGI = {8: "PEGI 3", 9: "PEGI 7", 10: "PEGI 12", 11: "PEGI 16", 12: "PEGI 18"}
ESRB = {
    1: "ESRB RP", 2: "ESRB EC", 3: "ESRB E", 4: "ESRB E10+", 5: "ESRB T",
    6: "ESRB M", 7: "ESRB AO",
}
_ORG_PEGI = 2
_ORG_ESRB = 1
_TAMANO_COVER = "t_cover_big"  # sustituye a t_thumb en images.igdb.com


class IgdbError(Exception):
    """Error base del conector IGDB."""


class IgdbNoConfigurado(IgdbError):
    """Faltan IGDB_CLIENT_ID / IGDB_CLIENT_SECRET."""


class IgdbApiError(IgdbError):
    """La API respondió un error HTTP."""

    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class AgeRating:
    organization: int | None = None
    rating_category: int | None = None


@dataclass
class Cover:
    url: str | None = None


@dataclass
class JuegoIgdb:
    """Resultado de búsqueda IGDB (subconjunto con lo que usa la ficha)."""

    name: str
    slug: str | None = None
    summary: str | None = None
    rating: float | None = None
    aggregated_rating: float | None = None
    first_release_date: int | None = None
    url: str | None = None
    cover: Cover = field(default_factory=Cover)
    platforms: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    age_ratings: list[AgeRating] = field(default_factory=list)

    @classmethod
    def from_raw(cls, d: dict[str, Any]) -> "JuegoIgdb":
        cover = d.get("cover") or {}
        return cls(
            name=str(d.get("name") or ""),
            slug=d.get("slug"),
            summary=d.get("summary"),
            rating=d.get("rating"),
            aggregated_rating=d.get("aggregated_rating"),
            first_release_date=d.get("first_release_date"),
            url=d.get("url"),
            cover=Cover(url=cover.get("url")),
            platforms=[p.get("name") for p in d.get("platforms", []) if p.get("name")],
            genres=[g.get("name") for g in d.get("genres", []) if g.get("name")],
            age_ratings=[
                AgeRating(a.get("organization"), a.get("rating_category"))
                for a in d.get("age_ratings", [])
                if isinstance(a, dict)
            ],
        )


def _imagen_igdb(url: str | None, tamano: str = _TAMANO_COVER) -> str | None:
    """Normaliza una URL de images.igdb.com (// → https) al tamaño pedido."""
    if not url:
        return None
    if "images.igdb.com" in url:
        url = url.replace("t_thumb", tamano)
    if url.startswith("//"):
        url = "https:" + url
    return url


def _fecha_iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d")


def _pegi_desde(juego: JuegoIgdb) -> str | None:
    """PEGI (con fallback ESRB) de la clasificación por edad de IGDB."""
    for edad in juego.age_ratings:
        if edad.organization == _ORG_PEGI and edad.rating_category:
            return PEGI.get(edad.rating_category)
    for edad in juego.age_ratings:
        if edad.organization == _ORG_ESRB and edad.rating_category:
            return ESRB.get(edad.rating_category)
    return None


# NOTA IMPORTANTE (a diferencia de un-conector-anterior): aquí NO hay listas
# de "frases/tokens de ruido" (plataforma/edición/condición) que se eliminen del
# título. Allí los productos venían de tiendas ("Pokémon Escarlata · Nintendo
# Switch", "Seminuevo"…) y la consola se registraba aparte. Aquí las carpetas
# MEGA ya son NOMBRES REALES de juegos, y palabras como "Switch", "Edition",
# "Collection", "Remastered", "Ultimate", "Us" o "HD" pueden ser parte del
# título (1-2 Switch, Among Us, ACE COMBAT 7 DELUXE EDITION…): borrarlas rompe
# el match. Solo se normaliza: acentos, apóstrofes, puntuación, ruido de escena
# ([v1.0], año entre paréntesis) y se mantienen todas las palabras.

# Numerales romanos sueltos → arábigos. Se excluyen "v" y "x" (GTA V, Pokémon X).
_ROMANOS = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7",
    "viii": "8", "ix": "9",
}

# Alias regionales (Europa/EE.UU. y castellano → título IGDB canónico).
_ALIASES_TITULO = {
    "animal crossing lets go to the city": "animal crossing city folk",
    "animal crossing lets go": "animal crossing city folk",
    "pokemon purpura": "pokemon violet",
    "pokemon escarlata": "pokemon scarlet",
    "pokemon espada": "pokemon sword",
    "pokemon escudo": "pokemon shield",
    "pokemon sol": "pokemon sun",
    "pokemon luna": "pokemon moon",
    "pokemon sol y luna": "pokemon sun and moon",
    "pokemon ultrasol": "pokemon ultra sun",
    "pokemon ultraluna": "pokemon ultra moon",
    "pokemon rubi": "pokemon ruby",
    "pokemon zafiro": "pokemon sapphire",
    "pokemon esmeralda": "pokemon emerald",
    "pokemon rubi omega": "pokemon omega ruby",
    "pokemon zafiro alfa": "pokemon alpha sapphire",
    "pokemon diamante": "pokemon diamond",
    "pokemon perla": "pokemon pearl",
    "pokemon platino": "pokemon platinum",
    "pokemon diamante brillante": "pokemon brilliant diamond",
    "pokemon perla reluciente": "pokemon shining pearl",
    "pokemon negro": "pokemon black",
    "pokemon blanco": "pokemon white",
    "pokemon negro 2": "pokemon black 2",
    "pokemon blanco 2": "pokemon white 2",
    "pokemon negra": "pokemon black",
    "pokemon blanca": "pokemon white",
    "pokemon negra 2": "pokemon black 2",
    "pokemon blanca 2": "pokemon white 2",
    "pokemon rojo fuego": "pokemon fire red",
    "pokemon verde hoja": "pokemon leaf green",
    "pokemon rojo": "pokemon red",
    "pokemon roja": "pokemon red",
    "pokemon azul": "pokemon blue",
    "pokemon amarillo": "pokemon yellow",
    "pokemon amarilla pikachu": "pokemon yellow",
    "pokemon oro": "pokemon gold",
    "pokemon plata": "pokemon silver",
    "pokemon cristal": "pokemon crystal",
    "pokemon conquista": "pokemon conquest",
    "pokemon heartgold": "pokemon heartgold",
    "pokemon oro heartgold": "pokemon heartgold",
    "pokemon soulsilver": "pokemon soulsilver",
    "pokemon plata soulsilver": "pokemon soulsilver",
    "leyendas pokemon arceus": "pokemon legends arceus",
    "leyendas pokemon z a": "pokemon legends z a",
    "pokemon detective pikachu": "pokemon detective pikachu",
    "detective pikachu el regreso": "detective pikachu returns",
}

def titulo_para_igdb(nombre: str) -> str:
    """Normaliza un título (NOMBRE REAL de juego) para buscar en IGDB.

    A diferencia de un-conector-anterior NO elimina palabras de plataforma/
    edición/condición (aquí no hay ruido de tienda; "Switch", "Edition",
    "Collection"… pueden ser parte del título real). Solo:
      - apóstrofes y acentos normalizados,
      - puntuación → espacios,
      - ruido de escena: "(2023)", "[v1.0]"…
      - romanos sueltos (i→1, vii→7; nunca v/x) y alias regionales (Pokémon).
    """
    import re

    texto = _titulo_busqueda_libre(nombre)
    limpio = " ".join(_ROMANOS.get(p, p) for p in texto.split())
    limpio = re.sub(r"^(?:the\s+)+", "", limpio)
    return _ALIASES_TITULO.get(limpio, limpio)


def _tokens_extra(termino_limpio: str, candidato: str) -> int:
    """Tokens del candidato que sobran frente a la consulta (penaliza bundles)."""
    n_consulta = len(termino_limpio.split())
    n_candidato = len(titulo_para_igdb(candidato).split())
    return max(0, n_candidato - n_consulta)


def _puntuacion(termino_limpio: str, candidato: str) -> int:
    """Puntuación por subcadena común de tokens entre la consulta y el candidato."""
    consulta = termino_limpio.split()
    nombre = titulo_para_igdb(candidato).split()
    mejor = 0
    for i in range(len(consulta)):
        for j in range(len(nombre)):
            k = 0
            while (
                i + k < len(consulta)
                and j + k < len(nombre)
                and consulta[i + k] == nombre[j + k]
            ):
                k += 1
            if k > mejor:
                mejor = k
    return mejor


def _confianza(original_limpio: str, candidato: str) -> tuple[int, float]:
    """(tokens compartidos, ratio) entre la consulta ORIGINAL y el candidato."""
    consulta = set(original_limpio.split())
    nombre = set(titulo_para_igdb(candidato).split())
    if not consulta:
        return 0, 0.0
    inter = len(consulta & nombre)
    return inter, inter / len(consulta)


def _es_confiable(original_limpio: str, candidato: str) -> bool:
    """True si el match es lo bastante específico (evita fichas incorrectas)."""
    inter, ratio = _confianza(original_limpio, candidato)
    if ratio < 0.5:
        return False
    return inter >= 2 or len(original_limpio.split()) <= 2


def ficha_desde_juego(juego: JuegoIgdb) -> dict[str, Any]:
    """Ficha oficial normalizada (mismo esquema que `cache_igdb.ficha` de gamechecker)."""
    return {
        "nombre_oficial": juego.name,
        "slug": juego.slug,
        "descripcion": juego.summary,
        "caratula": _imagen_igdb(juego.cover.url if juego.cover else None),
        "rating": round(juego.rating, 1) if juego.rating is not None else None,
        "rating_agregado": (
            round(juego.aggregated_rating, 1) if juego.aggregated_rating is not None else None
        ),
        "pegi": _pegi_desde(juego),
        "plataformas": juego.platforms,
        "generos": juego.genres,
        "fecha_lanzamiento": _fecha_iso(juego.first_release_date),
        "url_igdb": f"https://www.igdb.com/games/{juego.slug}" if juego.slug else None,
    }


# `status` de IGDB: 0 cancelado, 2 anunciado, 3 beta, 4 alfa, 5 en desarrollo…
_ESTADOS_IGDB = {
    0: "Cancelado", 2: "Anunciado", 3: "Beta", 4: "Alfa", 5: "En desarrollo",
    6: "Rumoreado", 7: "Retrasado",
}
# Categorías de webs de IGDB (v4 `websites.category`).
_CATEGORIA_WEB = {
    1: "Web oficial", 2: "Web", 3: "Wikipedia", 4: "Facebook", 5: "Twitter",
    6: "Twitch", 8: "Instagram", 9: "YouTube", 10: "iPhone", 11: "iPad",
    12: "Android", 13: "Steam", 14: "Reddit", 15: "Itch", 16: "Epic Games",
    17: "GOG", 18: "Discord", 19: "ProtonDB",
}


def _ficha_detallada_desde(datos: dict[str, Any]) -> dict[str, Any]:
    """Ficha IGDB COMPLETA de un juego (página de detalle).

    Espejo de `_ficha_detallada_desde` de un-conector-anterior: sinopsis,
    argumento, ratings, votos, PEGI/ESRB, plataformas, géneros, temas, modos,
    perspectivas, palabras clave, desarrollador/editor, capturas, vídeos
    (YouTube), webs, similares, colección, franquicia y estado.
    """

    def _pegi(raw_ratings: list | None) -> str | None:
        for r in raw_ratings or []:
            if r.get("organization") == _ORG_PEGI and r.get("rating_category"):
                return PEGI.get(r["rating_category"])
        for r in raw_ratings or []:
            if r.get("organization") == _ORG_ESRB and r.get("rating_category"):
                return ESRB.get(r["rating_category"])
        return None

    def _num(v: Any) -> float | None:
        return round(float(v), 1) if v is not None else None

    cover = (datos.get("cover") or {}).get("url")
    companias = [
        (c.get("company") or {}).get("name")
        for c in datos.get("involved_companies", []) if c.get("company")
    ]
    desarrollador = next(
        (n for n in companias if n), None
    )  # fallback simple; mejor abajo por flags
    publicador = None
    for c in datos.get("involved_companies", []):
        if c.get("developer") and c.get("company", {}).get("name"):
            desarrollador = c["company"]["name"]
        if c.get("publisher") and c.get("company", {}).get("name"):
            publicador = c["company"]["name"]

    return {
        "ficha_v": 2,
        "nombre_oficial": datos.get("name"),
        "slug": datos.get("slug"),
        "descripcion": datos.get("summary"),        # sinopsis
        "argumento": datos.get("storyline") or None,  # historia detallada
        "caratula": _imagen_igdb(cover),
        "rating": _num(datos.get("rating")),
        "rating_agregado": _num(datos.get("aggregated_rating")),
        "rating_total": _num(datos.get("total_rating")),
        "votos": datos.get("rating_count"),
        "votos_total": datos.get("total_rating_count"),
        "pegi": _pegi(datos.get("age_ratings")),
        "plataformas": [p.get("name") for p in datos.get("platforms", []) if p.get("name")],
        "generos": [g.get("name") for g in datos.get("genres", []) if g.get("name")],
        "temas": [t.get("name") for t in datos.get("themes", []) if t.get("name")],
        "modos": [m.get("name") for m in datos.get("game_modes", []) if m.get("name")],
        "perspectivas": [
            p.get("name") for p in datos.get("player_perspectives", []) if p.get("name")
        ],
        "palabras_clave": [
            k.get("name") for k in datos.get("keywords", []) if k.get("name")
        ][:20],
        "desarrollador": desarrollador,
        "publicador": publicador,
        "fecha_lanzamiento": _fecha_iso(datos.get("first_release_date")),
        "estado": _ESTADOS_IGDB.get(datos.get("status")) if datos.get("status") is not None else None,
        "capturas": [
            _imagen_igdb(s.get("url"), "t_screenshot_huge")
            for s in datos.get("screenshots", []) if s.get("url")
        ],
        "videos": [
            {"nombre": v.get("name"), "video_id": v.get("video_id")}
            for v in datos.get("videos", []) if v.get("video_id")
        ],
        "webs": [
            {"categoria": _CATEGORIA_WEB.get(w.get("category"), "Web"), "url": w.get("url")}
            for w in datos.get("websites", []) if w.get("url")
        ],
        "similares": [
            {
                "nombre": s.get("name"),
                "slug": s.get("slug"),
                "caratula": _imagen_igdb((s.get("cover") or {}).get("url")),
                "rating": _num(s.get("rating")),
            }
            for s in datos.get("similar_games", []) if s.get("slug")
        ],
        "coleccion": min(
            (c.get("name") for c in datos.get("collections", []) if c.get("name")), key=len
        ) if datos.get("collections") else None,
        "franquicia": (datos.get("franchise") or {}).get("name"),
        "url_igdb": f"https://www.igdb.com/games/{datos.get('slug')}" if datos.get("slug") else None,
    }


_REGIONES_IGDB = {
    1: "Europa", 2: "Norteamérica", 3: "Australia", 4: "Nueva Zelanda",
    5: "Japón", 6: "China", 7: "Asia", 8: "Mundial",
}
_ORG_SISTEMA = {1: "ESRB", 2: "PEGI", 3: "CERO"}


def _texto_clasificacion(r: dict) -> str | None:
    """Texto legible de una clasificación de edad (PEGI/ESRB/CERO…)."""
    org = r.get("organization")
    cat = r.get("rating_category")
    if org == _ORG_PEGI:
        return PEGI.get(cat) or "PEGI"
    if org == _ORG_ESRB:
        return ESRB.get(cat) or "ESRB"
    if org == 3:  # CERO (sin mapeo numérico público fiable)
        return "CERO"
    return None


def _lanzamientos_desde(rows: list | None) -> list[dict]:
    """Lanzamientos por plataforma (detalle 'Releases' de la web de IGDB)."""
    salida: list[dict] = []
    vistos: set[tuple] = set()
    for r in sorted(rows or [], key=lambda x: (x.get("date") is None, x.get("date") or 0)):
        plataforma = (r.get("platform") or {}).get("name")
        clave = (plataforma, r.get("human"), r.get("date"))
        if not plataforma or clave in vistos:
            continue
        vistos.add(clave)
        salida.append({
            "plataforma": plataforma,
            "fecha": _fecha_iso(r.get("date")),
            "humano": r.get("human"),
            "region": _REGIONES_IGDB.get(r.get("region")) if r.get("region") is not None else None,
        })
    return salida[:60]


def _etiqueta_url(url: str) -> str:
    """Etiqueta humana de un enlace externo por su dominio (Steam/Xbox/…)."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    parejas = [
        ("store.steampowered", "Steam"), ("steam", "Steam"), ("gog.com", "GOG"),
        ("xbox.com", "Xbox"), ("microsoft.com", "Microsoft"),
        ("playstation.com", "PlayStation"), ("nintendo.com", "Nintendo"),
        ("nintendo.es", "Nintendo"), ("epicgames", "Epic Games"),
        ("twitch.tv", "Twitch"), ("youtube.com", "YouTube"), ("discord", "Discord"),
        ("reddit.com", "Reddit"), ("wikipedia.org", "Wikipedia"),
        ("play.google.com", "Google Play"), ("apps.apple.com", "App Store"),
    ]
    for marca, etiqueta in parejas:
        if marca in host:
            return etiqueta
    return host.removeprefix("www.") or url[:40]


def _enlaces_desde(websites: list | None, externos: list | None) -> list[dict]:
    """Fusión de websites + external_games (Steam/Xbox/PlayStation/Nintendo…)."""
    salida: list[dict] = []
    vistos: set[str] = set()
    for w in websites or []:
        url = w.get("url")
        if not url or url in vistos:
            continue
        vistos.add(url)
        categoria = _CATEGORIA_WEB.get(w.get("category"), "Web")
        etiqueta = categoria if categoria != "Web" else _etiqueta_url(url)
        salida.append({"etiqueta": etiqueta, "url": url})
    for e in externos or []:
        url = e.get("url")
        if not url or url in vistos:
            continue
        vistos.add(url)
        salida.append({"etiqueta": _etiqueta_url(url), "url": url})
    return salida[:50]


def _idiomas_desde(rows: list | None) -> list[str]:
    """Idiomas soportados (language_supports), únicos y por orden."""
    salida: list[str] = []
    vistos: set[str] = set()
    for r in rows or []:
        nombre = (r.get("language") or {}).get("name")
        locale = (r.get("language") or {}).get("locale")
        clave = nombre or locale or ""
        if clave and clave not in vistos:
            vistos.add(clave)
            salida.append(nombre or locale)
    return salida[:40]


# Series/colecciones comerciales que anteceden al título real (p. ej.
# "ACA NEOGEO METAL SLUG 3" → "Metal Slug 3"). Si la búsqueda con el prefijo no
# encuentra nada, se reintenta sin él.
_SERIES_PREFIJOS = (
    "aca neogeo selection vol ", "aca neo geo selection vol ", "aca neogeo ",
    "aca neo geo ", "arcade archives ", "neo geo ", "sega ages ", "konami arcade "
    "classics ", "capcom arcade stadium ", "namco museum ", "atari flashback ",
    "nintendo switch ", "nintendo classic mini ",
)


def _titulo_busqueda_libre(nombre: str) -> str:
    """Variante de búsqueda que NO elimina palabras de plataforma/consola.

    Necesaria porque a veces la consola forma parte del título real
    ("1-2-Switch", "Nintendo Switch Sports"…). Quita solo lo claramente
    accesorio: paréntesis con año, apóstrofes, ruido de escena y espacios.
    """
    import re
    import unicodedata

    nombre = re.sub(r"[’‘`´']", "", nombre)
    texto = unicodedata.normalize("NFKD", nombre)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"\(\d{4}\)", " ", texto)          # "(2023)" → espacio
    texto = re.sub(r"\(?\[?(?:v\d+(?:\.\d+)?)\]?\)?", " ", texto)  # "[v1.0.2]"
    texto = re.sub(r"[^a-z0-9 ]+", " ", texto)
    limpio = " ".join(texto.split())
    return re.sub(r"^(?:the\s+)+", "", limpio)


def _variantes_para(limpio: str) -> list[str]:
    """Variantes de búsqueda: el título limpio y sus versiones sin prefijo de serie."""
    variantes = [limpio]
    baja = limpio.lower()
    for prefijo in _SERIES_PREFIJOS:
        if baja.startswith(prefijo):
            resto = limpio[len(prefijo):].strip()
            if resto and resto not in variantes:
                variantes.append(resto)
    # Sin la coletilla típica de lanzamiento por volúmenes ("vol 1"/"vol. 1").
    import re

    sin_vol = re.sub(r"\s+(?:vol\.?|volume)\s*\d+$", "", limpio).strip()
    if sin_vol and sin_vol != limpio and sin_vol not in variantes:
        variantes.append(sin_vol)
    return variantes[:4]


# ============================================================================
# MATCHER v3 — recuperación de títulos que IGDB escribe distinto
# ============================================================================
# Objetivo: recuperar los "miss" producidos por:
#   1) letras espaciadas de escena  ("S N I P E R"  →  "sniper")
#   2) números/edición al final      ("Blasphemous 1", "… Special Edition")
#   3) palabras pegadas/diferentes   ("BOXBOY BOXGIRL" → "Box Boy! + Box Girl!")
# Mantiene SIEMPRE la puerta v2 (no rompe los 5.167 matches correctos) y solo
# añade vías de aceptación conservadoras (identidad casi perfecta).
# ============================================================================

# Palabras finales decorativas: al quitarlas del final, el núcleo sigue siendo
# el MISMO juego (se usa solo si el núcleo coincide EXACTO con un candidato).
_DECORATIVOS_FINAL = {
    "nintendo", "switch", "edition", "deluxe", "special", "ultimate",
    "complete", "collection", "remastered", "anniversary", "plus",
    "vol", "volume", "select", "gold", "platinum", "hd",
}


def _compactar_letras_espaciadas(texto: str) -> str:
    """Une letras sueltas consecutivas: 's n i p e r' → 'sniper' (no toca
    palabras reales ni números: 'c a r d s rpg' → 'cards rpg')."""
    out: list[str] = []
    buf: list[str] = []
    for tok in texto.split():
        if len(tok) == 1 and tok.isalpha():
            buf.append(tok)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(tok)
    if buf:
        out.append("".join(buf))
    return " ".join(out)


def _pegado(texto: str) -> str:
    """Cadena sin espacios (compara 'boxboy boxgirl' con 'Box Boy! + Box Girl!')."""
    return "".join(texto.split())


def _ratio_pegado(a: str, b: str) -> float:
    """Similitud de caracteres (difflib) entre dos cadenas sin espacios."""
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()


def _quitar_decorativos(tokens: list[str]) -> list[str]:
    while tokens and tokens[-1] in _DECORATIVOS_FINAL:
        tokens = tokens[:-1]
    return tokens


def _encaja_core_decorativo(limpio: str, candidato: str) -> bool:
    """True si el candidato es EXACTAMENTE el núcleo del título local tras
    quitarle la coletilla decorativa final (p. ej. 'Beyond Hanwell Nintendo
    Switch Edition' → candidato 'Beyond Hanwell'). Núcleo de ≥2 palabras para
    no arriesgarse con títulos de una sola palabra."""
    core = _quitar_decorativos(_compactar_letras_espaciadas(limpio).split())
    cand = _compactar_letras_espaciadas(titulo_para_igdb(candidato)).split()
    return len(core) >= 2 and core == cand


def _aceptable_v3(limpio: str, candidato: str) -> bool:
    """Puerta relajada v3 (conservadora: NO admite con 2 palabras sueltas).

    Solo acepta:
    - identidad casi perfecta por caracteres (pegado): 'Blasphemous 1'→'Blasphemous',
      'Bubbles Bubbles Ocean'→'bubble bubble ocean', 'BOXBOY BOXGIRL'→'Box Boy!…';
    - parecido fuerte con ancla compartida (p. ej. 'S.T.A.L.K.E.R. … Enhanced
      Edition', donde el final decorativo alarga la cadena);
    - nombres de una palabra casi idénticos.
    Así NO se cuelan juegos distintos que solo comparten 2 palabras
    ('Before the Night' NO cae en 'Nights of Azure', 'DOOM 1993' NO en 'Doom II').
    """
    comp_orig = _compactar_letras_espaciadas(limpio)
    comp_cand = _compactar_letras_espaciadas(titulo_para_igdb(candidato))
    j_orig = _pegado(comp_orig)
    j_cand = _pegado(comp_cand)
    if not j_orig or not j_cand:
        return False
    ratio = _ratio_pegado(j_orig, j_cand)
    toks_orig = comp_orig.split()
    toks_cand = comp_cand.split()
    # Identidad (o casi) por caracteres.
    if ratio >= 0.8:
        return True
    # Parecido fuerte con al menos una palabra ancla compartida.
    if ratio >= 0.72 and len(j_orig) >= 8 and (set(toks_orig) & set(toks_cand)):
        return True
    # Nombres de una palabra casi idénticos.
    if len(toks_orig) == 1 and len(toks_cand) <= 2 and ratio >= 0.85:
        return True
    return False


class IgdbConnector:
    """Acceso a los metadatos oficiales de IGDB (busca por nombre de juego).

    Igual que el `IgdbConnector` de un-conector-anterior: token cacheados por
    proceso con renovación automática, throttle de 0.3 s entre llamadas y
    reintento de tokens de IGDB con caída de tokens finales + puerta de
    confianza para no adjuntar fichas incorrectas.
    """

    def __init__(self, *, settings: Settings | None = None,
                 transport: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._http = transport or httpx.Client(
            headers={"User-Agent": self.settings.user_agent, "Accept": "application/json"},
            timeout=self.settings.http_timeout,
        )
        self._token: str | None = None
        self._throttle = threading.Lock()
        self._ultima_llamada = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "IgdbConnector":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Configuración y token ───────────────────────────────────────────────
    def configurado(self) -> bool:
        return bool(self.settings.igdb_client_id and self.settings.igdb_client_secret)

    def _esperar_throttle(self) -> None:
        with self._throttle:
            restante = self.settings.igdb_throttle_seconds - (
                time.monotonic() - self._ultima_llamada
            )
            if restante > 0:
                time.sleep(restante)
            self._ultima_llamada = time.monotonic()

    def _obtener_token(self) -> str:
        if self._token:
            return self._token
        if not self.configurado():
            raise IgdbNoConfigurado(
                "IGDB no configurado: define IGDB_CLIENT_ID e IGDB_CLIENT_SECRET en .env"
            )
        self._esperar_throttle()
        respuesta = self._http.post(
            self.settings.igdb_token_url,
            params={
                "client_id": self.settings.igdb_client_id,
                "client_secret": self.settings.igdb_client_secret,
                "grant_type": "client_credentials",
            },
        )
        if respuesta.status_code != 200:
            raise IgdbApiError(respuesta.status_code, f"OAuth falló: {respuesta.text[:200]}")
        self._token = str(respuesta.json()["access_token"])
        return self._token

    def _post(self, endpoint: str, query: str) -> list[dict]:
        """POST Apicalypse a /v4/{endpoint} con reintento si el token caduca."""
        for intento in range(2):
            token = self._obtener_token()
            self._esperar_throttle()
            respuesta = self._http.post(
                f"{self.settings.igdb_base_url}/{endpoint}",
                headers={
                    "Client-ID": self.settings.igdb_client_id,
                    "Authorization": f"Bearer {token}",
                },
                content=query,
            )
            if respuesta.status_code == 401 and intento == 0:
                self._token = None  # token caducado → renovar y reintentar
                continue
            if respuesta.status_code != 200:
                raise IgdbApiError(
                    respuesta.status_code,
                    f"IGDB /{endpoint} → {respuesta.status_code}: {respuesta.text[:200]}",
                )
            return respuesta.json()
        raise IgdbApiError(401, "IGDB rechazó el token tras renovarlo")

    # ── Búsqueda y match ────────────────────────────────────────────────────
    def buscar_juego(self, termino: str, *, limite: int = 5) -> list[JuegoIgdb]:
        """Busca juegos por nombre (`search` de IGDB, ordenado por relevancia)."""
        termino_limpio = termino.replace('"', "'").strip()
        if not termino_limpio:
            return []
        query = (
            "fields name,slug,summary,rating,aggregated_rating,first_release_date,url,"
            "cover.url,age_ratings.organization,age_ratings.rating_category,"
            "platforms.name,genres.name; "
            f'search "{termino_limpio}"; limit {limite};'
        )
        datos = self._post("games", query)
        return [JuegoIgdb.from_raw(x) for x in datos]

    def mejor_juego(self, termino_limpio: str, *, limite: int = 5) -> JuegoIgdb | None:
        """Devuelve el candidato más parecido a la consulta (puntuación + tokens)."""
        juegos = self.buscar_juego(termino_limpio, limite=limite)
        if not juegos:
            return None
        return max(
            juegos,
            key=lambda j: (
                _puntuacion(termino_limpio, j.name or ""),
                -_tokens_extra(termino_limpio, j.name or ""),
            ),
        )

    def mejor_juego_con_reintento(
        self, termino_limpio: str, *, limite: int = 5, max_intentos: int = 5,
    ) -> JuegoIgdb | None:
        """Como `mejor_juego`, suelta tokens finales si no hay match, con puerta
        de confianza (rechaza matches débiles). `max_intentos` acota llamadas."""
        tokens = termino_limpio.split()
        minimo = min(2, len(tokens))
        while tokens and len(tokens) >= len(termino_limpio.split()) - max_intentos:
            consulta = " ".join(tokens)
            juego = self.mejor_juego(consulta, limite=limite)
            if juego and _es_confiable(termino_limpio, juego.name or ""):
                return juego
            tokens = tokens[:-1]
            if len(tokens) < minimo:
                break
        return None

    def ficha(self, juego: JuegoIgdb) -> dict[str, Any]:
        """Ficha oficial (diccionario JSON para persistir)."""
        return ficha_desde_juego(juego)

    def mejor_juego_ampliado(self, limpio: str, *, nombre: str | None = None,
                             limite: int = 8, max_intentos: int = 5) -> JuegoIgdb | None:
        """Como `mejor_juego_con_reintento` pero probando variantes.

        Orden de búsqueda:
          1. término LIBRE (conserva consolas que son parte del título real,
             p. ej. "1 2 switch" → 1-2-Switch, no Langrisser),
          2. título limpio y versiones sin prefijo de serie ("ACA NEOGEO …"),
          3. coletillas de volumen ("vol 1").
        Todo con la misma puerta de confianza frente al título original.
        """
        variantes: list[str] = []
        if nombre:
            libre = _titulo_busqueda_libre(nombre)
            if libre and libre != limpio:
                variantes.append(libre)
        for v in _variantes_para(limpio):
            if v not in variantes:
                variantes.append(v)
        for variante in variantes:
            juego = self.mejor_juego_con_reintento(variante, limite=limite,
                                                   max_intentos=max_intentos)
            if juego and _es_confiable(limpio, juego.name or ""):
                return juego
        return None

    def mejor_juego_v3(self, limpio: str, *, nombre: str | None = None,
                       limite: int = 8) -> JuegoIgdb | None:
        """Match v3 (recuperación): conserva la puerta v2 y añade vías seguras.

        Orden:
          1) puerta v2 sobre el conjunto de candidatos devueltos por IGDB;
          2) núcleo decorativo exacto (p. ej. 'Beyond Hanwell Nintendo Switch
             Edition' → 'Beyond Hanwell');
          3) puerta relajada `_aceptable_v3` (identidad casi perfecta).
        Las variantes de búsqueda compactan letras espaciadas y recortan colas
        numéricas/de edición para que IGDB devuelva el juego real.
        """
        variantes: list[str] = []
        def _add(v: str | None) -> None:
            v = (v or "").strip()
            if v and v not in variantes:
                variantes.append(v)

        if nombre:
            _add(_compactar_letras_espaciadas(_titulo_busqueda_libre(nombre)))
        _add(limpio)
        comp = _compactar_letras_espaciadas(limpio)
        _add(comp)
        toks = comp.split()
        while len(toks) > 2:          # cola larga → núcleo progresivo
            toks = toks[:-1]
            _add(" ".join(toks))
        if len(toks) == 2 and toks[-1].isdigit():   # 'Blasphemous 1' → núcleo
            _add(toks[0])
        variantes = variantes[:7]

        vistos: dict[str, JuegoIgdb] = {}
        for v in variantes:
            try:
                resultados = self.buscar_juego(v, limite=limite)
            except IgdbApiError:
                continue
            for j in resultados:
                if j.slug and j.slug not in vistos:
                    vistos[j.slug] = j
        if not vistos:
            return None
        juegos = list(vistos.values())

        # 1) Núcleo decorativo exacto (candidato == núcleo del original).
        orig = _compactar_letras_espaciadas(limpio).split()
        for v in variantes:
            vcore = v.split()
            if len(vcore) < 2 or orig[:len(vcore)] != vcore:
                continue
            caidos = orig[len(vcore):]
            if not caidos or not all(t in _DECORATIVOS_FINAL for t in caidos):
                continue
            for j in juegos:
                if _encaja_core_decorativo(limpio, j.name or ""):
                    return j

        # 2) Puerta v3 estricta (identidad por caracteres, conservadora).
        def _sim(j: JuegoIgdb) -> float:
            return _ratio_pegado(
                _pegado(_compactar_letras_espaciadas(limpio)),
                _pegado(_compactar_letras_espaciadas(titulo_para_igdb(j.name or ""))),
            )

        buenos = [j for j in juegos if _aceptable_v3(limpio, j.name or "")]
        if buenos:
            return max(buenos, key=_sim)
        return None

    def ficha_detallada(self, slug: str) -> dict[str, Any] | None:
        """Ficha IGDB COMPLETA de un juego por slug.

        Incluye además del núcleo: lanzamientos por plataforma (Releases),
        enlaces (websites + tiendas externas), clasificaciones de edad y
        idiomas soportados. None si el slug no existe.
        """
        query = (
            "fields id,name,slug,summary,storyline,rating,total_rating,"
            "aggregated_rating,rating_count,total_rating_count,first_release_date,url,"
            "cover.url,screenshots.url,artworks.url,videos.name,videos.video_id,"
            "websites.category,websites.url,"
            "release_dates.category,release_dates.date,release_dates.human,"
            "release_dates.region,release_dates.platform.name,"
            "external_games.category,external_games.url,"
            "game_modes.name,player_perspectives.name,themes.name,keywords.name,"
            "involved_companies.company.name,involved_companies.developer,"
            "involved_companies.publisher,"
            "similar_games.name,similar_games.slug,similar_games.cover.url,"
            "similar_games.rating,collections.name,franchise.name,genres.name,"
            "platforms.name,age_ratings.organization,age_ratings.rating_category,"
            "status,url; "
            f'where slug = "{slug}"; limit 1;'
        )
        datos = self._post("games", query)
        if not datos:
            return None
        fila = datos[0]
        base = _ficha_detallada_desde(fila)
        # Artworks (imagen hero HD real de IGDB) a tamaño 1080p.
        artworks = [
            _imagen_igdb(a.get("url"), "t_1080p")
            for a in fila.get("artworks", []) if a.get("url")
        ]
        base["artworks"] = artworks[:20]
        base["hero_imagen"] = artworks[0] if artworks else None
        base["lanzamientos"] = _lanzamientos_desde(fila.get("release_dates"))
        base["enlaces"] = _enlaces_desde(fila.get("websites"), fila.get("external_games"))
        clasificaciones: list[dict] = []
        visto_clasif: set[tuple] = set()
        for r in fila.get("age_ratings", []):
            texto = _texto_clasificacion(r)
            sistema = _ORG_SISTEMA.get(r.get("organization"), "Clasificación")
            clave = (sistema, texto)
            if texto and clave not in visto_clasif:
                visto_clasif.add(clave)
                clasificaciones.append({"sistema": sistema, "texto": texto})
        base["clasificaciones"] = clasificaciones
        # Idioma(s) soportados: consulta secundaria por game-id (language_supports).
        gid = fila.get("id")
        base["idiomas_soporte"] = []
        if gid:
            try:
                langs = self._post(
                    "language_supports",
                    "fields game,language.name,language.locale; "
                    f"where game={gid}; limit 80;",
                )
                base["idiomas_soporte"] = _idiomas_desde(langs)
            except Exception:
                pass  # best-effort: el resto de la ficha se entrega igual
        return base


# Alias de compatibilidad (la primera versión del módulo se llamaba IgdbClient).
IgdbClient = IgdbConnector
