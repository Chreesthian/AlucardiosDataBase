#!/usr/bin/env python3
"""Genera los iconos PWA y el emblema de ALUCARDIOS con la identidad nueva.

Diseño "riso / dusk" (clon de charbeltannous.com adaptado al catálogo):
  - fondo tinta    #111314
  - monograma A    #f8ed43 (trazo grueso, esquinas rectas)
  - acento         #ff4060 (punto superior derecho)
  - líneas de archivo #f8ed43 translúcidas en la base

Todo se dibuja a 4x y se reduce con LANCZOS para bordes limpios, así que el
script no depende de fuentes ni de binarios externos:

    python3 frontend/scripts/gen_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]  # frontend/
PUBLIC = ROOT / "public"
ICONS = PUBLIC / "icons"
BRAND = PUBLIC / "brand"

INK = (17, 19, 20, 255)
YELLOW = (248, 237, 67, 255)
PINK = (255, 64, 96, 255)
YELLOW_SOFT = (248, 237, 67, 150)


def _mark(size: int, margin: float = 0.11, background: bool = True) -> Image.Image:
    """Dibuja el monograma en un lienzo cuadrado (4x supersampling)."""
    scale = 4
    side = size * scale
    canvas = Image.new("RGBA", (side, side), INK if background else (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    inset = side * margin
    box = side - inset * 2

    def p(x: float, y: float) -> tuple[float, float]:
        return (inset + box * x / 512.0, inset + box * y / 512.0)

    stroke = max(2, round(box * 54 / 512))
    cross = max(2, round(box * 46 / 512))

    # Las dos piernas de la A. Se dibujan por separado (sin "joint") para que
    # el vértice quede en punta y no en un bloque redondeado.
    draw.line([p(150, 430), p(256, 76)], fill=YELLOW, width=stroke)
    draw.line([p(362, 430), p(256, 76)], fill=YELLOW, width=stroke)
    # Travesaño.
    draw.line([p(198, 306), p(314, 306)], fill=YELLOW, width=cross)
    # Punto rosa (el "en línea" del sitio).
    cx, cy = p(404, 108)
    r = box * 0.052
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PINK)

    if background:
        # Líneas de "archivo" en la base, como las reglas del catálogo.
        for y in (448, 466, 484):
            draw.line([p(96, y), p(416, y)], fill=YELLOW_SOFT, width=max(1, round(box * 5 / 512)))

    # Esquinas limpias: el vértice del trazo puede salirse del área.
    return canvas.resize((size, size), Image.LANCZOS)


def _write_svg(path: Path, *, rounded: bool) -> None:
    bg = (
        '<rect width="512" height="512" rx="96" fill="#111314"/>'
        if rounded
        else '<rect width="512" height="512" fill="#111314"/>'
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Alucardios DataBase">
{bg}
<g stroke="#f8ed43" stroke-linecap="butt">
  <path d="M150 430 256 76" stroke-width="54"/>
  <path d="M362 430 256 76" stroke-width="54"/>
  <path d="M198 306h116" stroke-width="46"/>
</g>
<circle cx="404" cy="108" r="26" fill="#ff4060"/>
<g stroke="#f8ed43" stroke-width="5" opacity=".55">
  <path d="M96 448h320M96 466h320M96 484h320"/>
</g>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def _write_emblem_svg(path: Path) -> None:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Alucardios">
<g stroke="#f8ed43" stroke-linecap="butt">
  <path d="M150 430 256 76" stroke-width="54"/>
  <path d="M362 430 256 76" stroke-width="54"/>
  <path d="M198 306h116" stroke-width="46"/>
</g>
<circle cx="404" cy="108" r="26" fill="#ff4060"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    BRAND.mkdir(parents=True, exist_ok=True)

    _mark(192).save(ICONS / "icon-192.png", "PNG", optimize=True)
    _mark(512).save(ICONS / "icon-512.png", "PNG", optimize=True)
    # Maskable: más margen para que ningún recorte de Android coma la marca.
    _mark(512, margin=0.19).save(ICONS / "icon-maskable-512.png", "PNG", optimize=True)
    _mark(180, margin=0.13).save(ICONS / "apple-touch-icon.png", "PNG", optimize=True)

    # Emblema para la cabecera (transparente) y respaldo PNG de marca.
    _mark(512, margin=0.06, background=False).save(BRAND / "emblem.png", "PNG", optimize=True)
    _mark(512, margin=0.09).save(BRAND / "logo.png", "PNG", optimize=True)

    _write_svg(PUBLIC / "favicon.svg", rounded=True)
    _write_emblem_svg(BRAND / "emblem.svg")

    print(f"OK → {ICONS} · {BRAND} · favicon.svg")


if __name__ == "__main__":
    main()
