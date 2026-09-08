"""Dependencias FastAPI: sesión de BD por request.

`get_session` usa la fábrica de sesiones colgada del `app.state`
(inyectada por `create_app`), lo que permite a los tests sustituirla por una BD
temporal sin tocar el módulo global.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
