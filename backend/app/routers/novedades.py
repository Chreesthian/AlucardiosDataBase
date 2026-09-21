"""Endpoints de la sección "Novedades" (juegos y contenido nuevos).

Los eventos los registra `app.sync` en cada escaneo incremental a partir del
diff de rutas (y `app.novedades` puede reconstruir periodos anteriores).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import novedades as svc
from ..deps import get_session
from ..library import current_snapshot
from ..schemas import NovedadesOut, NovedadOut

router = APIRouter(prefix="/api/novedades", tags=["novedades"])


@router.get("", response_model=NovedadesOut)
def novedades(
    tipo: str | None = Query(
        default=None,
        description="Tipos separados por comas (juego_nuevo, update_nuevo, dlc_nuevo, contenido_nuevo)",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> NovedadesOut:
    tipos = tuple(t.strip() for t in (tipo or "").split(",") if t.strip()) or None
    snap = current_snapshot(session)
    sid = snap.id if snap else None
    filas, total = svc.listar(session, snapshot_id=sid, tipos=tipos, offset=offset, limit=limit)
    items = [NovedadOut(**i) for i in svc.serializar(session, sid or 0, filas)]
    return NovedadesOut(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        resumen=svc.resumen(session, snapshot_id=sid),
    )
