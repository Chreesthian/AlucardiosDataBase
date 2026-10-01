"""Endpoints de sincronización incremental (escaneo del volcado / MEGAcmd).

El refresco NUNCA reconstruye la BD: compara rutas y solo añade/borra/actualiza
lo que cambió, sin tocar el enriquecimiento IGDB de lo que persiste.

`/api/sync/status` informa además de la FRESCURA del volcado: si el refresco
automático de la fuente se para, la UI puede avisar en vez de mostrar una
biblioteca congelada como si estuviera al día. `/api/sync/cuentas` publica el
PRE-VUELO de rotación que escribe el host: cuando las credenciales de la semana
montan otra biblioteca el refresco se aborta (el catálogo no se toca) y la UI
tiene que poder decirlo.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
from ..schemas import CuentasEstadoOut, SnapshotOut, SyncRunOut, SyncStatusOut
from ..sync import frescura, refresh

router = APIRouter(prefix="/api/sync", tags=["sync"])


class DumpRequest(BaseModel):
    path: str | None = None


def _texto(valor: object) -> str | None:
    """Cadena no vacía del informe del pre-vuelo (sus campos pueden faltar)."""
    if not isinstance(valor, str):
        return None
    limpio = valor.strip()
    return limpio or None


def _lista_textos(valor: object) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()]


def _mapa_listas(valor: object) -> dict[str, list[str]]:
    if not isinstance(valor, dict):
        return {}
    return {str(clave): _lista_textos(lista) for clave, lista in valor.items()}


def _leer_informe(path: Path) -> dict | None:
    """Informe del pre-vuelo, o None si no existe / no es un objeto JSON legible."""
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _horas_desde(iso: str | None) -> float | None:
    """Horas transcurridas desde una marca ISO del informe (None si no se puede)."""
    if not iso:
        return None
    try:
        sello = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if sello.tzinfo is None:  # el script escribe con zona; sin ella, se asume UTC
        sello = sello.replace(tzinfo=UTC)
    return (datetime.now(UTC) - sello).total_seconds() / 3600


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


@router.get("/cuentas", response_model=CuentasEstadoOut)
def cuentas(request: Request) -> CuentasEstadoOut:
    """Pre-vuelo de rotación: ¿la cuenta MEGA de la semana ve la biblioteca?

    El informe lo escribe el host (`scripts/verificar_rotacion.py`, vía
    `make volcado` / `make volcado-cron`) en `data/estado_cuentas.json`. Sin
    informe se responde 200 con `disponible=False`: la ausencia no es un fallo
    (el pre-vuelo se puede desactivar con `ALUCARD_PREFLIGHT=0`), así que la UI
    solo debe alarmar cuando `ok` es False y no se forzó el vaciado.
    """
    cfg = getattr(request.app.state, "settings", None) or settings
    ruta = Path(cfg.resolved_estado_cuentas)
    informe = _leer_informe(ruta)
    if informe is None:
        return CuentasEstadoOut(
            disponible=False,
            aviso=(
                f"Sin informe de pre-vuelo en {ruta}: se escribe al refrescar el volcado "
                "en el host (`make volcado`)."
            ),
        )

    ok = bool(informe.get("ok", True))
    causa = _texto(informe.get("causa"))
    veredicto = _texto(informe.get("veredicto"))
    generado_en = _texto(informe.get("generado_en"))
    aviso = None
    if not ok:
        if causa == "sin_sesion":
            aviso = veredicto or (
                "No hay sesión MEGA activa: el pre-vuelo no pudo comprobar la biblioteca."
            )
        else:
            aviso = veredicto or (
                "Las credenciales de la semana no ven la biblioteca del volcado: no se ha "
                "aplicado ningún cambio al catálogo."
            )
    biblioteca = informe.get("biblioteca")
    nube_propia = informe.get("nube_propia")

    return CuentasEstadoOut(
        disponible=True,
        ok=ok,
        causa=causa,
        veredicto=veredicto,
        forzado=bool(informe.get("forzado", False)),
        cuenta=_texto(informe.get("cuenta")),
        generado_en=generado_en,
        edad_horas=_horas_desde(generado_en),
        volcado=_texto(informe.get("volcado")),
        biblioteca=biblioteca if isinstance(biblioteca, dict) else None,
        faltan_rutas=_lista_textos(informe.get("faltan_rutas")),
        faltan_buckets=_mapa_listas(informe.get("faltan_buckets")),
        nube_propia=nube_propia if isinstance(nube_propia, dict) else None,
        aviso=aviso,
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
            min_titulos_fraccion=cfg.sync_min_titulos_fraccion,
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
            min_titulos_fraccion=cfg.sync_min_titulos_fraccion,
        )
    except RuntimeError as exc:  # guard anti-vaciado / anti-truncado del sync
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncRunOut(ok=True, snapshot=None, resumen=resumen)
