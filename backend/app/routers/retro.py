"""Sección RETRO (ROMs): catálogo APARTE, con su propia BD y su propia página.

Las ROMs viven en OTRO in-share de MEGA (montado por otra cuenta del pool de
rotación) y se indexan en su propia BD (`data/retro.db`, `ALUCARD_RETRO_DB_PATH`)
a partir de su propio volcado (`mega_retro_contenido_MEGAcmd.txt`) con
`app.sync --coleccion retro` (lo orquesta `scripts/volcado_retro.sh`).

Estos endpoints NUNCA tocan el catálogo de Switch: leen `app.state.engine_retro`.
Un volcado de ROMs ingerido por error en el catálogo de Switch lo cortaría el
guard de sectores, y al revés no hay riesgo porque esta BD es independiente.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import library as svc
from .. import plataformas
from ..config import settings
from ..deps import get_session_retro
from ..enrich import FICHA_V, version
from ..ingest import COLECCION_RETRO
from ..models import Title
from ..parser import parse_file
from ..schemas import (
    BucketOut,
    FileOut,
    MetaOut,
    RetroStatusOut,
    SnapshotOut,
    SyncRunOut,
    TitleDetailOut,
    TitleListOut,
    TitleSummary,
    VersionOut,
)
from ..sync import frescura, refresh
from .sync import DumpRequest

router = APIRouter(prefix="/api/retro", tags=["retro"])


def _require_snapshot(session: Session):
    snap = svc.current_snapshot(session)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "La colección retro está vacía. Genera el volcado y escanéalo "
                "(`make volcado-retro`)."
            ),
        )
    return snap


@router.get("/meta", response_model=MetaOut)
def meta(session: Session = Depends(get_session_retro)) -> MetaOut:
    """Resumen de la colección retro (sistemas como 'buckets', por nombre)."""
    snap = svc.current_snapshot(session)
    if snap is None:
        return MetaOut(snapshot=None, titles=0, files=0, folders=0, bytes=0, covers=0, buckets=[])
    titles = session.query(Title).filter(Title.snapshot_id == snap.id).count()
    return MetaOut(
        snapshot=SnapshotOut.model_validate(snap),
        titles=titles,
        files=snap.file_count,
        folders=snap.folder_count,
        bytes=snap.total_size,
        covers=svc.count_covers(session, snap.id),
        buckets=[BucketOut(**b) for b in svc.list_buckets(session, snap.id, orden_alfabetico=True)],
    )


@router.get("/sistemas", response_model=list[BucketOut])
def sistemas(session: Session = Depends(get_session_retro)) -> list[BucketOut]:
    """Sistemas/plataformas del nivel 1 con su conteo y su NOMBRE OFICIAL.

    `letter` es el código del volcado (`ARC N-64`) y `plataforma` el sistema real
    (`Nintendo 64`, de `app.plataformas`): la UI usa el segundo y nunca enseña el
    código, que sigue siendo la identidad del contenido en MEGA.
    """
    snap = _require_snapshot(session)
    return [BucketOut(**b) for b in svc.list_buckets(session, snap.id, orden_alfabetico=True)]


@router.get("/titles", response_model=TitleListOut)
def titles(
    q: str | None = Query(default=None),
    sistema: str | None = Query(
        default=None,
        description=(
            "Plataforma del juego: su clave (`mega-drive`), su nombre oficial "
            "(`Sega Mega Drive/Genesis`) o el sistema del volcado (`ARC S3G4-…`)"
        ),
    ),
    sort: str = Query(
        default="canonico",
        description="canonico (nombre oficial IGDB) | name (fichero ROM) | year | size | files",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session_retro),
) -> TitleListOut:
    snap = _require_snapshot(session)
    # El "bucket" de la colección retro es el sistema, que se guarda en `letter`.
    # `sistema` puede llegar como clave canónica, nombre oficial o etiqueta del
    # volcado: `etiquetas_de` lo traduce a las etiquetas que hay en la BD (una
    # plataforma puede haberse llamado de varias formas entre volcados).
    # Por defecto se ordena por el NOMBRE OFICIAL de IGDB: el catálogo se lee
    # como un catálogo ("After Burner II"), no como ficheros (`After Burner.zip`).
    rows, total = svc.list_titles(
        session,
        snap.id,
        q=q,
        letters=plataformas.etiquetas_de(sistema) if sistema else None,
        sort=sort,
        offset=offset,
        limit=limit,
        letter_exact=True,
    )
    return TitleListOut(
        items=[TitleSummary.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/titles/{slug}", response_model=TitleDetailOut)
def title_detail(slug: str, session: Session = Depends(get_session_retro)) -> TitleDetailOut:
    """Ficha del juego retro: sistema, formatos, contenido y ficha IGDB.

    El enriquecimiento IGDB de esta colección lo hace SU worker
    (`backend-retro-enrich`, ver `app.enrich --coleccion retro`): cuando la ficha
    existe se publica igual que en el catálogo de Switch. Lo que NO hay aquí son
    descargas MEGA: la sesión activa de MEGAcmd es la de la biblioteca.
    """
    snap = _require_snapshot(session)
    title, structure = svc.title_detail(session, snap.id, slug)
    if title is None:
        raise HTTPException(status_code=404, detail=f"Juego retro no encontrado: {slug}")

    versions = [
        VersionOut(
            id=v["id"],
            name=v["name"],
            label=v["label"],
            size_bytes=v["size_bytes"],
            file_count=v["file_count"],
            folder_count=v["folder_count"],
            full_path=v.get("full_path"),
            files=[FileOut(**f) for f in v["files"]],
        )
        for v in (structure or {}).get("versions", [])
    ]
    remaining = [FileOut(**f) for f in (structure or {}).get("remaining_files", [])]
    ficha_payload: dict | None = None
    if title.igdb_json:
        try:
            data = json.loads(title.igdb_json)
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict) and not data.get("miss"):
            ficha_payload = data
    return TitleDetailOut(
        slug=title.slug,
        name=title.name,
        name_norm=title.name_norm,
        letter=title.letter,
        size_bytes=title.size_bytes,
        file_count=title.file_count,
        folder_count=title.folder_count,
        base_count=title.base_count,
        update_count=title.update_count,
        dlc_count=title.dlc_count,
        formats=svc.exts_list(title.ext_json),
        igdb_slug=title.igdb_slug,
        igdb_cover=title.igdb_cover,
        igdb_name=title.igdb_name,
        igdb_year=title.igdb_year,
        ficha=ficha_payload,
        versions=versions,
        remaining_files=remaining,
    )


@router.post("/dump", response_model=SyncRunOut)
def sync_from_dump(request: Request, body: DumpRequest | None = None) -> SyncRunOut:
    """Escanea el volcado retro (o `body.path`) y aplica el diff en SU BD.

    Es el equivalente retro de `POST /api/sync/dump`: el host refresca el volcado
    (`scripts/volcado_retro.sh`) y pide aquí el escaneo para que se aplique ya. El
    worker `backend-retro-sync` sigue siendo la red de seguridad (≤300 s).
    """
    cfg = getattr(request.app.state, "settings", None) or settings
    dump = Path(body.path) if (body and body.path) else Path(cfg.resolved_retro_dump)
    try:
        parsed = parse_file(dump)
    except FileNotFoundError:
        raise HTTPException(404, f"Volcado retro no encontrado: {dump}") from None
    try:
        resumen = refresh(
            request.app.state.engine_retro,
            parsed,
            kind="dump",
            source_path=str(dump),
            min_fraccion=cfg.sync_min_fraccion,
            min_titulos_fraccion=cfg.sync_min_titulos_fraccion,
            coleccion=COLECCION_RETRO,
        )
    except RuntimeError as exc:  # guard anti-vaciado / anti-truncado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)


def _enriquecimiento(session: Session, snapshot_id: int) -> dict[str, int]:
    """Progreso de la ficha IGDB de ESTA colección (worker `backend-retro-enrich`).

    Mismo criterio que `GET /api/enrich/status` (`ficha_v 2` completa), pero sobre
    la BD retro: la sección puede decir cuánto falta sin tocar el catálogo Switch.
    """
    filas = session.execute(
        select(Title.igdb_cover, Title.igdb_json).where(Title.snapshot_id == snapshot_id)
    ).all()
    caratulas = sum(1 for cover, _ in filas if cover)
    enriquecidos = pendientes = sin_match = nombres = 0
    for _, raw in filas:
        data = None
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = None
        if isinstance(data, dict) and data.get("miss"):
            sin_match += 1
        elif isinstance(data, dict) and version(data) >= FICHA_V:
            enriquecidos += 1
        else:  # sin resolver, ilegible o solo ficha básica v1
            pendientes += 1
        # Nombre oficial: se cuenta de la FICHA (fuente de verdad), no de la
        # columna materializada, para que el progreso sea real aunque el worker
        # de enriquecimiento aún no haya hecho su pase de puesta al día.
        if isinstance(data, dict) and not data.get("miss") and data.get("nombre_oficial"):
            nombres += 1
    return {
        "caratulas": caratulas,
        "enriquecidos": enriquecidos,
        "pendientes_enrich": pendientes,
        "sin_match": sin_match,
        "con_nombre_oficial": nombres,
    }


@router.get("/status", response_model=RetroStatusOut)
def status(request: Request, session: Session = Depends(get_session_retro)) -> RetroStatusOut:
    """Frescura del volcado retro y tamaño de su catálogo (para avisar en la UI)."""
    cfg = getattr(request.app.state, "settings", None) or settings
    dump = Path(cfg.resolved_retro_dump)
    fresca = frescura(dump, cfg.sync_max_edad_horas)
    snap = svc.current_snapshot(session)
    juegos = session.query(Title).filter(Title.snapshot_id == snap.id).count() if snap else 0
    sistemas = len(svc.list_buckets(session, snap.id, orden_alfabetico=True)) if snap else 0
    enr = (
        _enriquecimiento(session, snap.id)
        if snap
        else {
            "caratulas": 0,
            "enriquecidos": 0,
            "pendientes_enrich": 0,
            "sin_match": 0,
            "con_nombre_oficial": 0,
        }
    )
    aviso = None
    if snap is None:
        aviso = "Sin catálogo retro todavía: ejecuta `make volcado-retro`."
    elif not dump.exists() or fresca["obsoleto"]:
        aviso = (
            "El volcado retro está ausente o caducado: la sección se está quedando "
            "congelada (revisa `make volcado-retro` y su cron)."
        )
    return RetroStatusOut(
        disponible=snap is not None,
        snapshot=SnapshotOut.model_validate(snap) if snap else None,
        juegos=juegos,
        sistemas=sistemas,
        volcado=str(dump),
        volcado_existe=dump.exists(),
        volcado_generated_at=fresca["generated_at"],
        volcado_fuente=fresca["fuente"],
        volcado_age_hours=fresca["edad_horas"],
        volcado_max_edad_horas=cfg.sync_max_edad_horas,
        volcado_obsoleto=fresca["obsoleto"],
        caratulas=enr["caratulas"],
        enriquecidos=enr["enriquecidos"],
        pendientes_enrich=enr["pendientes_enrich"],
        sin_match=enr["sin_match"],
        con_nombre_oficial=enr["con_nombre_oficial"],
        aviso=aviso,
    )
