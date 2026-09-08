#!/usr/bin/env python3
"""Genera los iconos PNG de la PWA a partir del EMBLEMA oficial de Alucardio
(/public/brand/emblem.png, extraído de alucardianos.com).

    python3 frontend/scripts/gen_icons.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]          # frontend/
BRAND = ROOT / "public" / "brand" / "emblem.png"
OUT = ROOT / "public" / "icons"


def _redimensionar(tam: int, path: Path, fondo: str | None = None) -> None:
    fuente = Image.open(BRAND).convert("RGBA")
    if fondo is not None:
        lienzo = Image.new("RGBA", (tam, tam), fondo)
        fuente = fuente.resize((int(tam * 0.78), int(tam * 0.78)), Image.LANCZOS)
        lienzo.alpha_composite(fuente, ((tam - fuente.width) // 2,
                                        (tam - fuente.height) // 2))
        lienzo.save(path, "PNG")
        return
    fuente.thumbnail((tam, tam), Image.LANCZOS)
    lienzo = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    lienzo.alpha_composite(fuente, ((tam - fuente.width) // 2,
                                    (tam - fuente.height) // 2))
    lienzo.save(path, "PNG")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _redimensionar(192, OUT / "icon-192.png")
    _redimensionar(512, OUT / "icon-512.png")
    # Maskable: el emblema sobre fondo blanco a sangre completa (recorte seguro).
    _redimensionar(512, OUT / "icon-maskable-512.png", fondo="#FFFFFF")
    print(f"OK → {OUT}")


if __name__ == "__main__":
    main()
