"""Novedades de la biblioteca: juegos nuevos y contenido nuevo por escaneo.

Diseño:
  - `registrar_novedades()` la invoca `app.sync` tras aplicar el diff de rutas:
    agrupa los archivos nuevos por título y deja un evento por
    (título, tipo, versión) en la tabla `novedades`.
  - Clasificación con `ingest.classify_version`: `U-PD…` → `update_nuevo`,
    `D-LC…` → `dlc_nuevo`, cualquier otro contenido nuevo dentro de un título
    existente → `contenido_nuevo`; y un título que aparece por primera vez →
    `juego_nuevo` (un único evento con todos sus archivos).
  - El registro es idempotente: si el evento ya existe se acumulan archivos,
    bytes y detalle, de modo que re-escanear (o reconstruir) no duplica filas.

CLI:
    uv run python -m app.novedades                    # lista las novedades
    uv run python -m app.novedades --out ../data/novedades.json
    uv run python -m app.novedades --desde ../volcado_anterior.txt

`--desde/--hasta` reconstruye las novedades de un periodo a partir del diff de
dos volcados: sirve para poblar la sección con semanas anteriores a la
existencia de la tabla.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import bucket_letter, classify_version
from .library import current_snapshot
from .models import Node, Novedad, Title
from .normalize import slugify
from .parser import Node as PNode
from .parser import parse_file
from .safefs import atomic_write_text

log = logging.getLogger("alucard.novedades")

TIPOS = ("juego_nuevo", "update_nuevo", "dlc_nuevo", "contenido_nuevo")
ETIQUETAS = {
    "juego_nuevo": "Juego nuevo",
    "update_nuevo": "Nuevos archivos de actualización",
    "dlc_nuevo": "Nuevos archivos de DLC",
    "contenido_nuevo": "Contenido nuevo",
}
# Tope de rutas guardadas por evento (el recuento real está en `archivos`).
DETALLE_MAX = 200


def titulo_de(path: str) -> str | None:
    """Ruta del título (sector/bucket/título) al que pertenece `path`."""
    partes = path.split("/")
    return "/".join(partes[:3]) if len(partes) >= 3 else None


def tipo_de(version: str | None, *, titulo_nuevo: bool) -> str:
    """Tipo de evento de una ruta nueva dentro de un título."""
    if titulo_nuevo:
        return "juego_nuevo"
    if version is None:
        return "contenido_nuevo"
    etiqueta = classify_version(version)
    return {"update": "update_nuevo", "dlc": "dlc_nuevo"}.get(etiqueta, "contenido_nuevo")


def _leer_detalle(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        datos = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in datos] if isinstance(datos, list) else []


def _fecha(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def titulos_por_slug(session: Session, snapshot_id: int, slugs: set[str]) -> dict[str, Title]:
    """Títulos vivos de la biblioteca indexados por slug (para hidratar eventos)."""
    if not slugs:
        return {}
    rows = (
        session.execute(
            select(Title).where(Title.snapshot_id == snapshot_id, Title.slug.in_(sorted(slugs)))
        )
        .scalars()
        .all()
    )
    return {t.slug: t for t in rows}


@dataclass(frozen=True)
class RefTitulo:
    """Datos mínimos del título para asociar un evento (de la BD o del volcado)."""

    slug: str
    name: str
    letter: str
    igdb_cover: str | None


def _ref_de(
    titulo_path: str,
    nodos: dict[str, PNode],
    titulos: dict[str, Title],
    por_slug: dict[str, Title],
) -> RefTitulo | None:
    """Título al que pertenece una ruta del volcado.

    Normalmente sale de la tabla `titles`; si el título no está en la biblioteca
    (p. ej. al reconstruir un periodo con un volcado posterior, o si ya se
    eliminó) se sintetiza desde el propio volcado para no perder el evento.
    """
    t = titulos.get(titulo_path)
    if t is not None:
        return RefTitulo(t.slug, t.name, t.letter, t.igdb_cover)
    nodo = nodos.get(titulo_path)
    if nodo is None:
        return None
    partes = titulo_path.split("/")
    letra = bucket_letter(partes[1]) if len(partes) > 1 else "#"
    slug = slugify(nodo.name)
    previo = por_slug.get(slug)
    return RefTitulo(slug, nodo.name, letra or "#", previo.igdb_cover if previo else None)


def registrar_novedades(
    session: Session,
    snapshot_id: int,
    anadidos: list[str],
    nodos: dict[str, PNode],
    *,
    detectada_en: datetime | None = None,
) -> int:
    """Registra en `novedades` los archivos nuevos de un escaneo.

    `anadidos` son las rutas nuevas y `nodos` el mapa ruta → nodo del volcado
    nuevo (lo construye `app.sync._collect`). Devuelve el número de eventos
    creados (los ya existentes se acumulan).
    """
    if not anadidos:
        return 0
    momento = detectada_en or datetime.now(UTC)
    nuevos = set(anadidos)

    filas = session.execute(
        select(Node.path, Title)
        .join(Title, Title.node_id == Node.id)
        .where(Node.snapshot_id == snapshot_id)
    ).all()
    titulos = dict(filas)
    por_slug = {t.slug: t for _, t in filas}

    agrupado: dict[tuple[str, str, str | None], dict] = {}
    for path in anadidos:
        nodo = nodos.get(path)
        if nodo is None or nodo.is_folder:  # solo los archivos suman archivos/bytes
            continue
        titulo_path = titulo_de(path)
        ref = _ref_de(titulo_path, nodos, titulos, por_slug) if titulo_path else None
        if ref is None:
            continue  # contenido fuera de un título (raíces, buckets, backups…)
        es_nuevo = titulo_path in nuevos
        partes = path.split("/")
        version = None if (es_nuevo or len(partes) <= 3) else partes[3]
        clave = (ref.slug, tipo_de(version, titulo_nuevo=es_nuevo), version)
        acc = agrupado.setdefault(clave, {"ref": ref, "archivos": []})
        acc["archivos"].append((path[len(titulo_path) + 1 :], nodo.size))

    creados = 0
    for (slug, tipo, version), acc in agrupado.items():
        ref: RefTitulo = acc["ref"]
        pares: list[tuple[str, int]] = acc["archivos"]
        cond_version = Novedad.version.is_(None) if version is None else Novedad.version == version
        existente = (
            session.execute(
                select(Novedad).where(
                    Novedad.snapshot_id == snapshot_id,
                    Novedad.slug == slug,
                    Novedad.tipo == tipo,
                    cond_version,
                )
            )
            .scalars()
            .first()
        )
        if existente is not None:
            previo = _leer_detalle(existente.detalle_json)
            # Idempotencia: si el detalle guardado está completo y ya contiene
            # todos los archivos del evento, un re-escaneo (o una reconstrucción
            # repetida) no debe duplicar contadores.
            if len(previo) == existente.archivos and all(rel in set(previo) for rel, _ in pares):
                continue
            vistos = set(previo)
            nuevos_pares = [(rel, size) for rel, size in pares if rel not in vistos]
            existente.archivos += len(nuevos_pares)
            existente.bytes_nuevos += sum(size for _, size in nuevos_pares)
            existente.detectada_en = momento
            existente.detalle_json = json.dumps(
                [*previo, *(rel for rel, _ in nuevos_pares)][:DETALLE_MAX], ensure_ascii=False
            )
            if ref.igdb_cover:
                existente.igdb_cover = ref.igdb_cover
            continue
        session.add(
            Novedad(
                snapshot_id=snapshot_id,
                slug=slug,
                name=ref.name,
                letter=ref.letter,
                tipo=tipo,
                version=version,
                archivos=len(pares),
                bytes_nuevos=sum(size for _, size in pares),
                detalle_json=json.dumps(
                    [rel for rel, _ in pares][:DETALLE_MAX], ensure_ascii=False
                ),
                igdb_cover=ref.igdb_cover,
                detectada_en=momento,
            )
        )
        creados += 1
    session.flush()
    log.info("novedades registradas: %d evento(s) nuevo(s)", creados)
    return creados


def listar(
    session: Session,
    *,
    snapshot_id: int | None = None,
    tipos: tuple[str, ...] | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[Novedad], int]:
    """Novedades más recientes primero, con filtro opcional por tipo(s)."""
    stmt = select(Novedad)
    cuenta = select(func.count(Novedad.id))
    conds = []
    if snapshot_id is not None:
        conds.append(Novedad.snapshot_id == snapshot_id)
    if tipos:
        conds.append(Novedad.tipo.in_(tipos))
    for cond in conds:
        stmt = stmt.where(cond)
        cuenta = cuenta.where(cond)
    total = session.execute(cuenta).scalar_one()
    rows = (
        session.execute(
            stmt.order_by(Novedad.detectada_en.desc(), Novedad.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def resumen(session: Session, *, snapshot_id: int | None = None) -> dict:
    """Contadores por tipo (para la cabecera de la sección)."""
    stmt = select(Novedad.tipo, func.count(Novedad.id))
    if snapshot_id is not None:
        stmt = stmt.where(Novedad.snapshot_id == snapshot_id)
    por_tipo = {tipo: int(n) for tipo, n in session.execute(stmt.group_by(Novedad.tipo)).all()}
    completo = {tipo: por_tipo.get(tipo, 0) for tipo in TIPOS}
    return {
        "total": sum(completo.values()),
        "por_tipo": completo,
        "juegos_nuevos": completo["juego_nuevo"],
        "actualizaciones": completo["update_nuevo"] + completo["dlc_nuevo"],
    }


def serializar(session: Session, snapshot_id: int, filas: list[Novedad]) -> list[dict]:
    """Items para la API/JSON, hidratados con los datos vivos del título."""
    por_slug = titulos_por_slug(session, snapshot_id, {f.slug for f in filas})
    items: list[dict] = []
    for f in filas:
        t = por_slug.get(f.slug)
        items.append(
            {
                "id": f.id,
                "tipo": f.tipo,
                "slug": f.slug,
                "name": f.name,
                "letter": f.letter,
                "version": f.version,
                "archivos": f.archivos,
                "bytes_nuevos": f.bytes_nuevos,
                "detalle": _leer_detalle(f.detalle_json),
                "igdb_cover": (t.igdb_cover if t is not None else None) or f.igdb_cover,
                "detectada_en": f.detectada_en.isoformat(),
                "vigente": t is not None,
                "titulo": (
                    None
                    if t is None
                    else {
                        "slug": t.slug,
                        "name": t.name,
                        "letter": t.letter,
                        "size_bytes": t.size_bytes,
                        "file_count": t.file_count,
                        "folder_count": t.folder_count,
                        "base_count": t.base_count,
                        "update_count": t.update_count,
                        "dlc_count": t.dlc_count,
                        "other_count": t.other_count,
                        "ext_json": t.ext_json,
                        "igdb_slug": t.igdb_slug,
                        "igdb_cover": t.igdb_cover,
                    }
                ),
            }
        )
    return items


def reconstruir(
    session: Session,
    snapshot_id: int,
    desde: Path,
    hasta: Path,
    *,
    fecha: str | None = None,
) -> int:
    """Registra las novedades del diff entre dos volcados (histórico).

    `fecha` (ISO) permite fijar la fecha de detección; por defecto se usa la del
    volcado nuevo y, si no la trae, la actual.
    """
    from .sync import _collect  # import local para evitar el ciclo con app.sync

    viejo, nuevo = parse_file(desde), parse_file(hasta)
    rutas_viejas, rutas_nuevas = _collect(viejo), _collect(nuevo)
    anadidos = sorted(set(rutas_nuevas) - set(rutas_viejas))
    detectada = _fecha(fecha) or _fecha(nuevo.generated_at) or datetime.now(UTC)
    print(
        f"   diff {desde.name} → {hasta.name}: +{len(anadidos)} rutas "
        f"({len(set(rutas_nuevas) - set(rutas_viejas))} de {len(rutas_nuevas)})"
    )
    return registrar_novedades(session, snapshot_id, anadidos, rutas_nuevas, detectada_en=detectada)


def _volcado(path: Path) -> Path:
    p = path.expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"Volcado no encontrado: {p}")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Novedades: juegos y contenido nuevos de la biblioteca"
    )
    ap.add_argument("--db", default=None, help="Ruta SQLite (def. data/alucard.db)")
    ap.add_argument("--desde", default=None, help="Volcado anterior: reconstruye el periodo")
    ap.add_argument(
        "--hasta", default=None, help="Volcado nuevo (def. el volcado configurado en settings)"
    )
    ap.add_argument("--fecha", default=None, help="Fecha ISO de detección (def. la del volcado)")
    ap.add_argument("--out", default=None, help="JSON de salida (p. ej. ../data/novedades.json)")
    ap.add_argument("--limit", type=int, default=100, help="Máximo de novedades a listar")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    url = (
        f"sqlite:///{Path(args.db).expanduser().resolve()}"
        if args.db
        else settings.resolved_database_url
    )
    create_schema(url)
    engine = build_engine(url)

    with Session(engine) as session:
        snap = current_snapshot(session)
        if snap is None:
            raise SystemExit("No hay snapshot: ejecuta primero la ingesta.")
        if args.desde:
            hasta = _volcado(Path(args.hasta)) if args.hasta else settings.resolved_dump
            creados = reconstruir(
                session, snap.id, _volcado(Path(args.desde)), hasta, fecha=args.fecha
            )
            session.commit()
            print(f"   {creados} evento(s) creado(s)")
        elif args.fecha:
            print("   (--fecha solo se usa junto con --desde)")

        filas, total = listar(session, snapshot_id=snap.id, limit=args.limit)
        res = resumen(session, snapshot_id=snap.id)
        print(
            f"Snapshot #{snap.id} · {total} novedad(es) · "
            + " · ".join(f"{t}={res['por_tipo'][t]}" for t in TIPOS)
        )
        for f in filas[:20]:
            version = f" ({f.version})" if f.version else ""
            print(
                f"   - [{ETIQUETAS.get(f.tipo, f.tipo)}] {f.name}{version} · "
                f"{f.archivos} archivo(s) · {f.detectada_en:%Y-%m-%d}"
            )
        if args.out:
            out = Path(args.out).expanduser().resolve()
            completas, _ = listar(session, snapshot_id=snap.id, limit=10_000)
            datos = {
                "meta": {
                    "snapshot_id": snap.id,
                    "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
                    **res,
                },
                "novedades": serializar(session, snap.id, completas),
            }
            atomic_write_text(out, json.dumps(datos, ensure_ascii=False, indent=1) + "\n")
            print(f"JSON → {out}")


if __name__ == "__main__":
    main()
