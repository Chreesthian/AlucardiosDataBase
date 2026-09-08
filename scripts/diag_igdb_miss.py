#!/usr/bin/env python3
"""Diagnóstico de títulos IGDB 'miss': re-consulta IGDB en vivo uno a uno.

Clasifica cada 'miss' almacenado en:
  - API_ERROR        → la API de IGDB falló al consultar (HTTP/red).
  - SIN_RESULTADOS   → IGDB devuelve 0 candidatos para todas las variantes.
  - RECUPERABLE      → existe candidato que SÍ pasa la puerta de confianza actual
                       (el matcher actual debería haberlo cogido: bug de búsqueda).
  - CERCA_SIN_PUERTA → hay candidatos parecidos pero la puerta de confianza los
                       rechaza (p. ej. números de versión/colección al final).

Uso (dentro del contenedor backend, con credenciales IGDB):
    python /tmp/diag_igdb_miss.py
Salida: /data/miss_diagnostico.json  (en el volumen) + resumen por stdout.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import build_engine
from app.enrich import _parse
from app.igdb import (
    IgdbApiError,
    IgdbConnector,
    _confianza,
    _es_confiable,
    _titulo_busqueda_libre,
    _variantes_para,
    titulo_para_igdb,
)
from app.models import Title


def _consultas(nombre: str) -> list[str]:
    qs: list[str] = []
    libre = _titulo_busqueda_libre(nombre)
    limpio = titulo_para_igdb(nombre)
    for x in (libre, limpio):
        if x and x not in qs:
            qs.append(x)
    # Variante sin el último token (caso típico 'Blasphemous 1', 'Aca Vol 3').
    tokens = limpio.split()
    if len(tokens) > 2:
        qs.append(" ".join(tokens[:-1]))
    for v in _variantes_para(limpio):
        if v not in qs:
            qs.append(v)
        if len(qs) >= 5:
            break
    return qs[:5]


def main() -> None:
    engine = build_engine(settings.resolved_database_url)
    with Session(engine) as s:
        filas = list(s.execute(select(Title).order_by(Title.name.asc())).scalars())
        misses = [t for t in filas if (_parse(t.igdb_json) or {}).get("miss")]
    print("diagnosticando", len(misses), "títulos miss")

    stats = {
        "api_error": 0,
        "sin_resultados": 0,
        "recuperable": 0,
        "cerca_sin_puerta": 0,
        "total": len(misses),
    }
    salida = []
    with IgdbConnector() as conn:
        for idx, t in enumerate(misses, 1):
            nombre = t.name
            limpio = titulo_para_igdb(nombre)
            candidatos: dict[str, dict] = {}
            api_err = None
            for q in _consultas(nombre):
                try:
                    raw = conn._post(
                        "games",
                        f'fields name,slug,platforms.name; search "{q}"; limit 8;',
                    )
                except IgdbApiError as exc:
                    api_err = f"{exc.status_code}: {exc}"
                except Exception as exc:  # noqa: BLE001 — red/timeout
                    api_err = f"{type(exc).__name__}: {exc}"
                if api_err:
                    break
                for x in raw:
                    slug = x.get("slug")
                    if not slug or slug in candidatos:
                        continue
                    inter, ratio = _confianza(limpio, x.get("name") or "")
                    candidatos[slug] = {
                        "name": x.get("name"),
                        "plataformas": [
                            p.get("name") for p in (x.get("platforms") or []) if p.get("name")
                        ],
                        "inter": inter,
                        "ratio": round(ratio, 2),
                    }

            if api_err:
                stats["api_error"] += 1
                categoria = "API_ERROR"
                ordenados = []
            elif not candidatos:
                stats["sin_resultados"] += 1
                categoria = "SIN_RESULTADOS"
                ordenados = []
            else:
                ordenados = sorted(candidatos.values(), key=lambda c: (-c["inter"], -c["ratio"]))
                if any(_es_confiable(limpio, c["name"]) for c in ordenados):
                    stats["recuperable"] += 1
                    categoria = "RECUPERABLE"
                else:
                    stats["cerca_sin_puerta"] += 1
                    categoria = "CERCA_SIN_PUERTA"

            salida.append(
                {
                    "title": nombre,
                    "limpio": limpio,
                    "categoria": categoria,
                    "api_error": api_err,
                    "candidatos": ordenados[:4] if not api_err else [],
                }
            )
            if idx % 20 == 0:
                print("progreso", idx, stats, flush=True)

    print("RESUMEN", json.dumps(stats, ensure_ascii=False), flush=True)
    with open("/data/miss_diagnostico.json", "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "titles": salida}, f, ensure_ascii=False, indent=1)
    print("OK /data/miss_diagnostico.json", flush=True)


if __name__ == "__main__":
    main()
