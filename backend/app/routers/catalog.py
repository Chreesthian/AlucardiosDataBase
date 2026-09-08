"""Catálogo interno clasificado (todo el contenido indexado)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import catalog as svc

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("")
def catalogo(request: Request) -> dict:
    """Resumen clasificado global: raíces, buckets, formatos, familias."""
    return svc.catalogar(request.app.state.engine)


@router.get("/folder")
def carpeta(path: str, request: Request) -> dict:
    """Información completa de una carpeta (path exacto) y su contenido."""
    info = svc.info_carpeta(request.app.state.engine, path)
    if info is None:
        raise HTTPException(404, f"Carpeta no encontrada: {path}")
    return info
