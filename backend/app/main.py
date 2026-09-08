"""Aplicación FastAPI (patrón análogo al de un proyecto anterior).

`create_app()` permite inyectar Settings en tests (BD temporal).
`app` es la instancia global que sirve uvicorn (`uvicorn app.main:app`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from . import __version__
from .config import Settings
from .config import settings as default_settings
from .db import build_engine, create_schema
from .routers import catalog, download, enrich, health, library, sync


def create_app(settings_: Settings | None = None) -> FastAPI:
    cfg = settings_ or default_settings
    database_url = cfg.resolved_database_url

    create_schema(database_url)
    engine = build_engine(database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_schema(database_url)
        yield

    app = FastAPI(
        title=cfg.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.database_url = database_url
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = cfg

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
