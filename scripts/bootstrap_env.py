#!/usr/bin/env python3
"""Copia las credenciales IGDB ("GamesDb") desde un `.env` de origen
al `.env` del backend (nunca imprime los valores).

Uso:
    python scripts/bootstrap_env.py [ruta_al_.env_de_origen]

Si no se pasa ruta, usa `$IGDB_SOURCE_ENV` si está definida; en otro caso busca
un `.env` de un proyecto hermano en el directorio del escritorio.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ENV = ROOT / "backend" / ".env"


def _default_source() -> Path:
    env = os.environ.get("IGDB_SOURCE_ENV")
    if env:
        return Path(env).expanduser()
    return ROOT.parent / "proyecto-previo" / ".env"


DEFAULT_SOURCE = _default_source()

MAP = {
    "IGDB_CLIENT_ID": "IGDB_CLIENT_ID",
    "IGDB_CLIENT_SECRET": "IGDB_CLIENT_SECRET",
}

_ENV_LINE = re.compile(r"^([A-Z0-9_]+)\s*=\s*(.*)$")


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ENV_LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    src = load_env(source)
    dst = load_env(BACKEND_ENV)

    copied = []
    for key, target in MAP.items():
        value = src.get(key)
        if value:
            dst[target] = value
            copied.append(key)

    lines = [f"{k}={v}" for k, v in sorted(dst.items())]
    BACKEND_ENV.parent.mkdir(parents=True, exist_ok=True)
    BACKEND_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if copied:
        print(f"Copiadas {len(copied)} credenciales IGDB desde {source} → {BACKEND_ENV}")
        for key in copied:
            print(f"  ✓ {key} (valor oculto)")
    else:
        print(
            f"No se encontraron credenciales IGDB en {source} (opcional, sin ellas la app sigue)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
