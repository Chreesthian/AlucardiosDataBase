#!/usr/bin/env python3
"""Agente host para que la UI Docker pueda actualizar la biblioteca MEGA.

El contenedor no puede usar MEGAcmd (sesión/socket del host), así que este
proceso corre en el equipo, reutiliza el pipeline existente y pide a la API del
catálogo que aplique el volcado ya refrescado. Las contraseñas MEGA se quedan en
el fichero privado del host; el contenedor solo ve el token del agente.

Uso:
    cd backend && uv run python ../scripts/agente_actualizacion.py \
        --sync-url http://127.0.0.1:7441/api/sync/dump

El token se genera en `data/update_agent.token` (0644: lo lee el contenedor;
NO es una contraseña MEGA). El agente escucha en un socket Unix
(`data/update_agent.sock`, 0666) y exige la cabecera
`X-Alucard-Update-Token`.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for _ruta in (str(ROOT), str(BACKEND), str(ROOT / "scripts")):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

from app.config import Settings  # noqa: E402
from app.mega_setup import HostMegaRunner, MegaSetupService  # noqa: E402
from app.routers.setup import router as setup_router  # noqa: E402
from app.safefs import atomic_write_text  # noqa: E402


def cargar_token(path: Path, override: str | None = None) -> str:
    """Token del agente; se crea la primera vez y se comparte con el contenedor."""
    if override:
        return override
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 16:
            with suppress(OSError):
                path.chmod(0o644)
            return token
    token = secrets.token_urlsafe(32)
    atomic_write_text(path, token + "\n")
    with suppress(OSError):
        path.chmod(0o644)
    return token

def crear_app(cfg: Settings, *, sync_url: str, token: str) -> FastAPI:
    def exigir_token(x_alucard_update_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_alucard_update_token, token):
            raise HTTPException(
                status_code=401,
                detail="Token de actualización no válido.",
            )

    app = FastAPI(title="AlucardiosDataBase · agente host", version="1")
    app.state.mega_setup = MegaSetupService(
        cfg,
        None,
        runner=HostMegaRunner(cfg, None, sync_url=sync_url),
    )
    app.include_router(setup_router, dependencies=[Depends(exigir_token)])

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Mismo criterio que la API principal: no reflejar el cuerpo recibido.
        if request.url.path.startswith("/api/setup/mega"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "Revisa las cuentas MEGA: faltan datos o el formato "
                        "no es válido."
                    )
                },
            )
        return await request_validation_exception_handler(request, exc)

    return app


def main() -> int:
    ap = argparse.ArgumentParser(description="Agente host de actualización MEGA")
    ap.add_argument(
        "--uds",
        default=os.environ.get("ALUCARD_UPDATE_AGENT_SOCKET", ""),
        help="socket Unix (def. data/update_agent.sock)",
    )
    ap.add_argument(
        "--sync-url",
        default=os.environ.get(
            "ALUCARD_SYNC_URL",
            "http://127.0.0.1:7441/api/sync/dump",
        ),
    )
    ap.add_argument("--token-path", default=None)
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    cfg = Settings()
    token_path = (
        Path(args.token_path).expanduser()
        if args.token_path
        else cfg.resolved_update_agent_token
    )
    token = cargar_token(token_path, args.token)
    if not token:
        print("No se pudo preparar el token del agente.", file=sys.stderr)
        return 2

    uds_path = (
        Path(args.uds).expanduser()
        if args.uds
        else cfg.resolved_update_agent_socket
    )
    uds_path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        uds_path.unlink()
    # El socket lo lee el contenedor (otro uid): 0666, protegido por el token.
    os.umask(0o111)

    print(
        f"agente de actualización en unix:{uds_path} "
        f"(token: {token_path}; API: {args.sync_url})",
        flush=True,
    )
    uvicorn.run(
        crear_app(cfg, sync_url=args.sync_url, token=token),
        uds=str(uds_path),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
