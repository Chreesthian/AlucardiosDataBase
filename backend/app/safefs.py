"""Escritura/lectura seguras (atómicas) para artefactos JSON de la BD.

Evita el corner case de que un lector (web, otro worker) se encuentre un JSON a
medio escribir si el proceso cae a mitad de `write_text`. Se escribe a un fichero
temporal en el mismo directorio y luego `os.replace` (atómico en el mismo fs).
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, texto: str, *, encoding: str = "utf-8") -> None:
    """Escribe `texto` en `path` de forma atómica (tmp + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(texto, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
