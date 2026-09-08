"""Estado del enriquecimiento IGDB (carátulas y fichas completas)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_session
from ..enrich import version
from ..library import current_snapshot
from ..models import Title

router = APIRouter(prefix="/api/enrich", tags=["enrich"])


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    snap = current_snapshot(session)
    if snap is None:
        return {
            "snapshot": None,
            "total": 0,
            "covers": 0,
            "fichas": 0,
            "pendientes": 0,
            "sin_match": 0,
        }
    rows = session.execute(
        select(Title.igdb_cover, Title.igdb_json).where(Title.snapshot_id == snap.id)
    ).all()
    total = len(rows)
    covers = sum(1 for c, _ in rows if c)
    fichas = 0
    pendientes = 0
    sin_match = 0
    for _, raw in rows:
        payload = _parse(raw)
        if payload is None:
            pendientes += 1
        elif payload.get("miss"):
            sin_match += 1
        elif version(payload) >= 2:
            fichas += 1
        else:
            pendientes += 1  # ficha v1 básica → falta ficha completa
    return {
        "snapshot": {"id": snap.id, "account": snap.account},
        "total": total,
        "covers": covers,
        "fichas_completas": fichas,
        "pendientes": pendientes,
        "sin_match": sin_match,
    }
