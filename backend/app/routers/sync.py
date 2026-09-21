"""Endpoints de sincronización incremental (escaneo del volcado / MEGAcmd).

El refresco NUNCA reconstruye la BD: compara rutas y solo añade/borra/actualiza
lo que cambió, sin tocar el enriquecimiento IGDB de lo que persiste.

`/api/sync/status` informa además de la FRESCURA del volcado: si el refresco
automático de la fuente se para, la UI puede avisar en vez de mostrar una
biblioteca congelada como si estuviera al día.
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
from ..sync import frescura, refresh

router = APIRouter(prefix="/api/sync", tags=["sync"])


class DumpRequest(BaseModel):
    path: str | None = None


@router.get("/status", response_model=SyncStatusOut)
def status(request: Request, session: Session = Depends(get_session)) -> SyncStatusOut:
    cfg = getattr(request.app.state, "settings", None) or settings
    snap = current_snapshot(session)
    probe = megacmd.probe()
    dump = cfg.resolved_dump
    fresca = frescura(dump, cfg.sync_max_edad_horas)
    ultimo = session.query(SyncLog).order_by(SyncLog.id.desc()).first()
    return SyncStatusOut(
        last_snapshot=SnapshotOut.model_validate(snap) if snap else None,
        configured_dump=str(dump),
        dump_exists=dump.exists(),
        dump_generated_at=fresca["generated_at"],
        dump_fuente=fresca["fuente"],
        dump_age_hours=fresca["edad_horas"],
        dump_max_edad_horas=fresca["max_edad_horas"],
        dump_obsoleto=fresca["obsoleto"],
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
    cfg = getattr(request.app.state, "settings", None) or settings
    dump = Path(body.path) if (body and body.path) else Path(cfg.resolved_dump)
    try:
        parsed = parse_file(dump)
    except FileNotFoundError:
        raise HTTPException(404, f"Volcado no encontrado: {dump}") from None
    try:
        resumen = refresh(
            request.app.state.engine,
            parsed,
            kind="dump",
            source_path=str(dump),
            min_fraccion=cfg.sync_min_fraccion,
        )
    except RuntimeError as exc:  # guard anti-vaciado / anti-truncado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)


@router.post("/megacmd", response_model=SyncRunOut)
def sync_from_megacmd(request: Request) -> SyncRunOut:
    """Vuelca la cuenta con MEGAcmd y aplica el escaneo incremental."""
    cfg = getattr(request.app.state, "settings", None) or settings
    try:
        text = megacmd.dump_tree()
    except megacmd.MegaCmdUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        resumen = refresh(
            request.app.state.engine,
            parse_text(text),
            kind="megacmd",
            source_path="megacmd",
            min_fraccion=cfg.sync_min_fraccion,
        )
    except RuntimeError as exc:  # guard anti-vaciado / anti-truncado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)
