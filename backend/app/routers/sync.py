"""Endpoints de sincronización incremental (escaneo del volcado / MEGAcmd).

El refresco NUNCA reconstruye la BD: compara rutas y solo añade/borra/actualiza
lo que cambió, sin tocar el enriquecimiento IGDB de lo que persiste.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import megacmd
from ..config import settings
from ..deps import get_session
from ..library import current_snapshot
from ..models import SyncLog
from ..parser import parse_file, parse_text
from ..schemas import SnapshotOut, SyncRunOut, SyncStatusOut
from ..sync import refresh

router = APIRouter(prefix="/api/sync", tags=["sync"])


class DumpRequest(BaseModel):
    path: str | None = None


@router.get("/status", response_model=SyncStatusOut)
def status(session: Session = Depends(get_session)) -> SyncStatusOut:
    snap = current_snapshot(session)
    probe = megacmd.probe()
    dump = settings.resolved_dump
    ultimo = session.query(SyncLog).order_by(SyncLog.id.desc()).first()
    return SyncStatusOut(
        last_snapshot=SnapshotOut.model_validate(snap) if snap else None,
        configured_dump=str(dump),
        dump_exists=dump.exists(),
        megacmd_available=probe.available,
        megacmd_binary=probe.binary,
        megacmd_error=probe.error,
        ultimo_escaneo=(
            {
                "id": ultimo.id,
                "ran_at": ultimo.ran_at.isoformat(),
                "kind": ultimo.kind,
                "added_files": ultimo.added_files,
                "removed_files": ultimo.removed_files,
                "changed_files": ultimo.changed_files,
                "added_folders": ultimo.added_folders,
                "removed_folders": ultimo.removed_folders,
            }
            if ultimo
            else None
        ),
    )


@router.post("/dump", response_model=SyncRunOut)
def sync_from_dump(request: Request, body: DumpRequest | None = None) -> SyncRunOut:
    """Escanea el volcado configurado (o `path`) y aplica el diff incremental."""
    dump = Path(body.path) if (body and body.path) else Path(settings.resolved_dump)
    try:
        parsed = parse_file(dump)
    except FileNotFoundError:
        raise HTTPException(404, f"Volcado no encontrado: {dump}") from None
    try:
        resumen = refresh(request.app.state.engine, parsed, kind="dump", source_path=str(dump))
    except RuntimeError as exc:  # guard anti-vaciado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)


@router.post("/megacmd", response_model=SyncRunOut)
def sync_from_megacmd(request: Request) -> SyncRunOut:
    """Vuelca la cuenta con MEGAcmd y aplica el escaneo incremental."""
    try:
        text = megacmd.dump_tree()
    except megacmd.MegaCmdUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        resumen = refresh(
            request.app.state.engine, parse_text(text), kind="megacmd", source_path="megacmd"
        )
    except RuntimeError as exc:  # guard anti-vaciado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)
