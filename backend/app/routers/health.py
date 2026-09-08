"""Healthcheck del servicio."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..deps import get_session
from ..models import Snapshot

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover  # noqa: BLE001
        db_ok = False
    snapshots = session.query(Snapshot).count()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "database": "ok" if db_ok else "error",
        "snapshots": snapshots,
    }
