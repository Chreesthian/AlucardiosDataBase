"""Auditoría de versiones 1:1 (local vs Nintendo).

Investigación (docs/INVESTIGACION_VERSIONES.md):
  - Local: base `B-ASE` + parches `U-PD/UP-D x.y.z…`; versión ofrecida = el máximo.
  - Nintendo EU SOLR resuelve NOMBRE → título-id Switch (`application_id_s`) y
    `nsuid`, pero NO expone la "versión actual" (vive en su CDN de actualizaciones;
    sin API pública). Se acepta una BD comunitaria título-id→versión (JSON) para
    el lado oficial.

El `1:1` = {carpeta → title-id} + {title-id → versión oficial} vs {máx U-PD}.

CLI:
    uv run python -m app.versiones
    uv run python -m app.versiones --oficiales data/oficial.json --out data/version_audit.json
    uv run python -m app.versiones --resolver 5
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .library import current_snapshot
from .models import Node, Title
from .safefs import atomic_write_text

_VER_FOLDER = re.compile(r"(?:U-PD|UP-D)\s*([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)
_TITLE_ID = re.compile(r"\[?([0-9A-Fa-f]{16})\]?")


def parse_version(texto: str) -> tuple[int, ...] | None:
    m = _VER_FOLDER.search(texto)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def vers_a_texto(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def title_id_de_nombre(nombre: str) -> str | None:
    m = _TITLE_ID.search(nombre)
    return m.group(1).upper() if m else None


def local_versions(engine) -> list[dict]:
    """Versión local por juego: base + parches y su máximo (`U-PD`)."""
    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            return []
        titulos = list(
            session.execute(
                select(Title).where(Title.snapshot_id == snap.id).order_by(Title.name_norm)
            ).scalars()
        )
        nodos = list(
            session.execute(
                select(Node).where(Node.snapshot_id == snap.id, Node.parent_id.is_not(None))
            ).scalars()
        )
        hijos: dict[int, list[Node]] = {}
        for n in nodos:
            hijos.setdefault(n.parent_id or 0, []).append(n)

        out = []
        for t in titulos:
            parches: list[tuple[int, ...]] = []
            base = False
            nsp_ids: set[str] = set()
            for ch in hijos.get(t.node_id, []):
                if ch.kind != "folder":
                    continue
                if re.match(r"^(B-ASE|BASE)\b", ch.name, re.IGNORECASE):
                    base = True
                v = parse_version(ch.name)
                if v:
                    parches.append(v)
                for f in hijos.get(ch.id, []):
                    if f.kind == "file" and f.ext in ("nsp", "nsz"):
                        tid = title_id_de_nombre(f.name)
                        if tid:
                            nsp_ids.add(tid)
            parches.sort()
            out.append(
                {
                    "slug": t.slug,
                    "nombre": t.name,
                    "base": base,
                    "versiones": [vers_a_texto(v) for v in parches],
                    "version_local": (
                        vers_a_texto(parches[-1]) if parches else ("1.0.0" if base else None)
                    ),
                    "title_ids": sorted(nsp_ids),
                }
            )
        return out


def nintendo_search(nombre: str, *, limite: int = 5) -> dict | None:
    """Resuelve un nombre de juego a su ficha de Nintendo Europe (title-id)."""
    with httpx.Client(timeout=20.0) as client:
        r = client.get(
            "https://searching.nintendo-europe.com/es/select",
            params={"q": nombre, "fq": "type:GAME", "rows": limite, "wt": "json"},
        )
        r.raise_for_status()
        docs = r.json()["response"]["docs"]
    limpio = re.sub(r"[^a-z0-9]+", " ", nombre.lower()).strip().split()
    for d in docs:
        sistemas = " ".join(d.get("system_names_txt") or []).lower()
        if "switch" not in sistemas and "3ds" not in sistemas:
            continue
        oficial = re.sub(r"[^a-z0-9]+", " ", (d.get("title") or "").lower()).strip().split()
        score = 0
        for i in range(len(limpio)):
            for j in range(len(oficial)):
                k = 0
                while (
                    i + k < len(limpio) and j + k < len(oficial) and limpio[i + k] == oficial[j + k]
                ):
                    k += 1
                score = max(score, k)
        if score >= max(2, len(limpio) - 1):
            return {
                "nombre": nombre,
                "titulo_oficial": d.get("title"),
                "title_id": (d.get("application_id_s") or "").upper() or None,
                "nsuid": (d.get("nsuid_txt") or [None])[0],
                "url": d.get("url"),
            }
    return None


def audit(local: list[dict], *, oficiales: dict[str, str] | None = None) -> dict:
    """Fusiona la versión local con la oficial por title-id (→ estado 1:1)."""
    oficiales = oficiales or {}
    items = []
    for it in local:
        oficial = None
        for tid in it["title_ids"]:
            if tid in oficiales:
                oficial = oficiales[tid]
                break
        if oficial:
            estado = "al_dia" if it["version_local"] == oficial else "desactualizado"
        else:
            estado = "desconocido"
        items.append({**it, "version_oficial_nintendo": oficial, "estado": estado})
    resumen = {"al_dia": 0, "desactualizado": 0, "desconocido": 0}
    for it in items:
        resumen[it["estado"]] += 1
    return {"items": items, "resumen": resumen}


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def _cargar_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _guardar_json(path: Path | None, data: dict) -> None:
    if path is None:
        return
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def pasada(
    engine,
    cache: dict,
    *,
    cache_path: Path | None = None,
    oficiales_path: Path | None = None,
    resolver: int = 0,
    out_path: Path | None = None,
    aviso_oficiales: bool = True,
    throttle: float = 0.3,
) -> dict:
    """Una pasada completa de la auditoría (resumible por cache)."""
    local = local_versions(engine)
    con_updates = sum(1 for juego in local if juego["versiones"])
    print(
        f"Juegos: {len(local)} · con parches: {con_updates} · solo base: "
        f"{len(local) - con_updates}"
    )

    oficiales: dict[str, str] = {}
    if oficiales_path is not None and oficiales_path.exists():
        raw = _cargar_json(oficiales_path)
        oficiales = {str(k).upper(): str(v) for k, v in raw.items()}
    elif oficiales_path is not None and aviso_oficiales:
        print(f"⚠ no existe {oficiales_path} (se continúa sin versiones oficiales)")

    nuevos = 0
    if resolver:
        for juego in local:
            if juego["slug"] in cache:
                r = cache[juego["slug"]]
                if r and r.get("title_id"):
                    juego["nintendo"] = r
                    juego["title_ids"].append(r["title_id"])
                continue
            if nuevos >= resolver:
                break
            try:
                r = nintendo_search(juego["nombre"])
            except Exception:  # noqa: BLE001 — fallo de red; se reintenta en otra pasada
                r = None
            if r and r.get("title_id"):
                cache[juego["slug"]] = r
                juego["nintendo"] = r
                juego["title_ids"].append(r["title_id"])
                nuevos += 1
                if cache_path and nuevos % 10 == 0:
                    _guardar_json(cache_path, cache)
            time.sleep(throttle)  # cortesía con Nintendo Europe
        if cache_path:
            _guardar_json(cache_path, cache)
        print(f"Nuevos resueltos en esta pasada: {nuevos} · cache total: {len(cache)}")

    res = audit(local, oficiales=oficiales)
    print("Estado:", res["resumen"])
    if out_path:
        _guardar_json(out_path, res)
        print(f"Auditoría → {out_path}")
    for it in res["items"][:6]:
        ninty = it.get("nintendo") or {}
        print(
            f"  · {it['nombre'][:40].ljust(42)} local={it['version_local']!s:8s} "
            f"oficial={it['version_oficial_nintendo']} id={ninty.get('title_id') or it['title_ids']} "
            f"→ {it['estado']}"
        )
    return {"nuevos": nuevos, "resumen": res["resumen"]}


def daemon(
    engine,
    *,
    cache_path: Path | None,
    oficiales_path: Path | None,
    out_path: Path | None,
    resolver: int,
    interval: int,
    throttle: float = 0.3,
) -> None:
    """Worker persistente de auditoría Nintendo (blindado para supervisión).

    - Reanudable: mantiene el checkpoint `cache` (slug → ficha Nintendo).
    - Cada pasada resuelve los juegos AÚN no verificados (los nuevos entran solos).
    - Si una llamada a Nintendo falla, se reintenta en la siguiente pasada.
    - Errores inesperados se registran y el bucle continúa (docker restart si cae).
    """
    print(f"[versiones-daemon] inicio: intervalo={interval}s · resolver/pasada={resolver}")
    cache = _cargar_json(cache_path)
    while True:
        try:
            stats = pasada(
                engine,
                cache,
                cache_path=cache_path,
                oficiales_path=oficiales_path,
                resolver=resolver,
                out_path=out_path,
                aviso_oficiales=False,
                throttle=throttle,
            )
            print(
                f"[versiones-daemon] pasada ok: nuevos={stats['nuevos']} "
                f"resumen={stats['resumen']} (siguiente en {interval}s)"
            )
        except KeyboardInterrupt:
            print("[versiones-daemon] detenido por señal.")
            return
        except Exception:  # noqa: BLE001 — el worker reintenta la pasada
            import traceback

            traceback.print_exc()
            print(f"[versiones-daemon] error en pasada; reintento en {interval}s")
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser(description="Auditoría de versiones local vs Nintendo")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--oficiales", default=None, help="JSON {TITLE_ID(16hex): 'x.y.z'} con versiones oficiales"
    )
    ap.add_argument(
        "--resolver", type=int, default=0, help="Resuelve N juegos a title-id (red a Nintendo EU)"
    )
    ap.add_argument(
        "--cache", default=None, help="JSON de checkpoint slug→ficha Nintendo (reanudable)"
    )
    ap.add_argument(
        "--daemon", action="store_true", help="Modo worker: pasadas en bucle (supervisado)"
    )
    ap.add_argument(
        "--interval", type=int, default=1800, help="Segundos entre pasadas en --daemon (def. 1800)"
    )
    args = ap.parse_args()

    engine = _make_engine(args.db)
    cache_path = Path(args.cache) if args.cache else None
    oficiales_path = Path(args.oficiales) if args.oficiales else None
    out_path = Path(args.out) if args.out else None

    if args.daemon:
        daemon(
            engine,
            cache_path=cache_path,
            oficiales_path=oficiales_path,
            out_path=out_path,
            resolver=args.resolver,
            interval=args.interval,
        )
        return

    cache = _cargar_json(cache_path)
    pasada(
        engine,
        cache,
        cache_path=cache_path,
        oficiales_path=oficiales_path,
        resolver=args.resolver,
        out_path=out_path,
        aviso_oficiales=True,
    )


if __name__ == "__main__":
    main()
