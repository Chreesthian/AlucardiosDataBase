"""Configuración de las cuentas MEGA y actualización del catálogo desde la UI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..mega_setup import (
    MegaCuenta,
    MegaSetupInvalid,
    MegaSetupService,
    MegaSetupUnavailable,
    MegaUpdateBusy,
)
from ..schemas import MegaSetupOut, MegaUpdateIn

router = APIRouter(prefix="/api/setup/mega", tags=["setup"])


def _service(request: Request) -> MegaSetupService:
    return request.app.state.mega_setup


@router.get("", response_model=MegaSetupOut)
def estado(request: Request) -> MegaSetupOut:
    """Estado de las cuentas y de la última actualización (nunca contraseñas)."""
    return MegaSetupOut.model_validate(_service(request).status())


@router.post("/update", response_model=MegaSetupOut, status_code=202)
def actualizar(request: Request, body: MegaUpdateIn | None = None) -> MegaSetupOut:
    """Guarda las tres cuentas (si vienen) y lanza la actualización en segundo plano."""
    cuentas = None
    if body and body.cuentas is not None:
        cuentas = [
            MegaCuenta(email=cuenta.email, password=cuenta.password)
            for cuenta in body.cuentas
        ]
    try:
        return MegaSetupOut.model_validate(_service(request).start(cuentas))
    except MegaSetupUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MegaSetupInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MegaUpdateBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
