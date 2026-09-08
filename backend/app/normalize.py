"""Helpers de normalización (nombres, slugs, extensiones).

`normalize` (sin acentos, minúsculas) se usa para búsquedas tolerantes de
nombres de juego (patrón heredado de un proyecto anterior).
"""

from __future__ import annotations

import re
import unicodedata

_SPECIALS = re.compile(r"[^\w\s-]|_")
_DASHES = re.compile(r"[-\s]+")


def fold(text: str) -> str:
    """Minúsculas sin acentos y signos raros (reserva espacios)."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_ = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_.lower()


def normalize(text: str) -> str:
    """Igual que `fold` pero colapsa separadores a un espacio."""
    return " ".join(_SPECIALS.sub(" ", fold(text)).split())


def slugify(text: str) -> str:
    """Slug legible para URLs (ASCII, guiones)."""
    s = _SPECIALS.sub("-", fold(text))
    s = _DASHES.sub("-", s).strip("-")
    return s or "untitled"


def ext_of(name: str) -> str | None:
    if "." not in name:
        return None
    return name.rsplit(".", 1)[1].strip().lower() or None


def format_bytes(n: int | float) -> str:
    """Tamaño legible (p. ej. 1.48 TiB)."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"
