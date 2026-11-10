"""Aplicación FastAPI (patrón análogo al de un proyecto anterior).

`create_app()` permite inyectar Settings en tests (BD temporal).
`app` es la instancia global que sirve uvicorn (`uvicorn app.main:app`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from . import __version__
from .config import Settings
from .config import settings as default_settings
from .db import build_engine, create_schema
from .mega_setup import MegaSetupService, RemoteMegaSetupService
from .routers import catalog, download, enrich, health, library, novedades, retro, setup, sync


def create_app(settings_: Settings | None = None) -> FastAPI:
    cfg = settings_ or default_settings
    database_url = cfg.resolved_database_url
    # La colección retro (ROMs) vive en SU PROPIA BD: así el catálogo de Switch no
    # se contamina ni comparte snapshots/novedades con una biblioteca que rota por
    # otra cuenta del pool (ver `app.ingest`).
    retro_url = cfg.resolved_retro_database_url

    create_schema(database_url)
    engine = build_engine(database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    create_schema(retro_url)
    engine_retro = build_engine(retro_url)
    session_factory_retro = sessionmaker(bind=engine_retro, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_schema(database_url)
        create_schema(retro_url)
        yield

    app = FastAPI(
        title=cfg.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.database_url = database_url
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.retro_database_url = retro_url
    app.state.engine_retro = engine_retro
    app.state.session_factory_retro = session_factory_retro
    app.state.settings = cfg
    # La actualización usa el mismo motor/BD; el runner comprueba si MEGAcmd
    # existe en ESTE equipo antes de aceptar credenciales. En Docker se delega
    # al agente host (ALUCARD_UPDATE_AGENT_URL) porque el contenedor no puede
    # acceder a la sesión MEGAcmd del equipo.
    if cfg.update_agent_url or cfg.update_agent_socket_path:
        app.state.mega_setup = RemoteMegaSetupService(cfg)
    else:
        app.state.mega_setup = MegaSetupService(cfg, engine)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_origin_regex=(
            r"https?://(localhost|127\.0\.0\.1|\[::1\]|"
            r"192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(library.router)
    app.include_router(sync.router)
    app.include_router(enrich.router)
    app.include_router(catalog.router)
    app.include_router(download.router)
    app.include_router(novedades.router)
    # Sección aparte: ROMs retro (otra BD, otro volcado, otra cuenta del pool).
    app.include_router(retro.router)
    app.include_router(setup.router)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        """No devolver el cuerpo inválido de la pantalla MEGA.

        Pydantic incluye `input` en algunos errores; para las cuentas eso podría
        reflejar una contraseña en la respuesta HTTP o en un log. El resto de la
        API conserva el comportamiento estándar de FastAPI.
        """
        if request.url.path.startswith("/api/setup/mega"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "Revisa las cuentas MEGA: faltan datos o el formato no es válido."
                },
            )
        return await request_validation_exception_handler(request, exc)

    @app.get("/")
    def root() -> dict:
        return {
            "name": cfg.app_name,
            "version": __version__,
            "docs": "/docs",
            "api": "/api/health",
        }

    return app


app = create_app()
