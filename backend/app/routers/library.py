"""Endpoints de la biblioteca (meta, buckets, títulos, detalle)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import library as svc
from ..deps import get_session
from ..models import Title
from ..schemas import (
    BucketOut,
    FileOut,
    MetaOut,
    SnapshotOut,
    TitleDetailOut,
    TitleListOut,
    TitleSummary,
    VersionOut,
)

router = APIRouter(prefix="/api", tags=["library"])


def _require_snapshot(session: Session):
    snap = svc.current_snapshot(session)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail="No hay ningún snapshot. Ejecuta la ingesta (uv run python -m app.ingest).",
        )
    return snap


@router.get("/meta", response_model=MetaOut)
def meta(session: Session = Depends(get_session)) -> MetaOut:
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
        buckets=[BucketOut(**b) for b in svc.list_buckets(session, snap.id)],
    )


@router.get("/buckets", response_model=list[BucketOut])
def buckets(session: Session = Depends(get_session)) -> list[BucketOut]:
    snap = _require_snapshot(session)
    return [BucketOut(**b) for b in svc.list_buckets(session, snap.id)]


@router.get("/titles", response_model=TitleListOut)
def titles(
    q: str | None = Query(default=None),
    letter: str | None = Query(default=None),
    sort: str = Query(default="name"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> TitleListOut:
    snap = _require_snapshot(session)
    rows, total = svc.list_titles(
        session,
        snap.id,
        q=q,
        letter=letter,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    return TitleListOut(
        items=[TitleSummary.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/titles/{slug}", response_model=TitleDetailOut)
def title_detail(slug: str, session: Session = Depends(get_session)) -> TitleDetailOut:
    snap = _require_snapshot(session)
    title, structure = svc.title_detail(session, snap.id, slug)
    if title is None:
        raise HTTPException(status_code=404, detail=f"Título no encontrado: {slug}")

    versions = []
    for v in (structure or {}).get("versions", []):
        versions.append(
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
        )
    remaining = [FileOut(**f) for f in (structure or {}).get("remaining_files", [])]
    # Ficha IGDB completa almacenada (solo si el título está enriquecido).
    ficha_payload: dict | None = None
    if title.igdb_json:
        import json as _json

        try:
            data = _json.loads(title.igdb_json)
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
        ficha=ficha_payload,
        versions=versions,
        remaining_files=remaining,
    )
