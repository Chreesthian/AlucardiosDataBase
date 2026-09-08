"""Wrapper de MEGAcmd: localización de binarios y volcado canónico.

En F0 se prepara la integración real: MEGAcmd debe estar instalado y con la
cuenta con sesión iniciada (servidor `megacmd`/socket en `~/.megaCmd`). El
módulo degrada con mensajes claros si el binario no está disponible, de modo
que el proyecto funciona 100% con el volcado `.txt` mientras tanto.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .config import settings


class MegaCmdUnavailable(RuntimeError):
    """MEGAcmd no está instalado o no es ejecutable."""


@dataclass
class MegaCmdInfo:
    available: bool
    binary: str | None
    version: str | None = None
    error: str | None = None


def _which(names: list[str]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def probe() -> MegaCmdInfo:
    binary = _which([settings.mega_ls_bin, "mega-ls", "megacmd", "mega-cmd"])
    if binary is None:
        return MegaCmdInfo(
            available=False,
            binary=None,
            error=(
                "MEGAcmd no está en el PATH. Instálalo y asegura sesión iniciada "
                "(ver ~/.megaCmd) para refrescar en vivo."
            ),
        )
    version = None
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
        version = (out.stdout or out.stderr or "").strip().splitlines()
        version = version[0] if version else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return MegaCmdInfo(available=True, binary=binary, version=version)


def export_link(remote_path: str, timeout: int | None = None) -> str:
    """Genera (o recupera) el enlace público MEGA de un nodo exacto.

    Usa `mega-export -a -f <ruta>` para crear el export si no existe (acepta los
    términos de copyright) y, si ya estaba exportado, lo recupera con una
    segunda llamada sin `-a`. Devuelve la URL `https://mega.nz/…`.
    """
    binary = _which(["mega-export", settings.mega_export_bin])
    if binary is None:
        raise MegaCmdUnavailable(
            "mega-export no está en el PATH: instala MEGAcmd para generar enlaces"
        )

    def _run(args: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout or settings.mega_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise MegaCmdUnavailable(
                f"mega-export agotó el tiempo ({settings.mega_timeout_s}s)"
            ) from exc
        except OSError as exc:
            raise MegaCmdUnavailable(str(exc)) from exc

    def _buscar(proc: subprocess.CompletedProcess) -> str | None:
        salida = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for linea in salida.splitlines():
            if "mega.nz" in linea:
                ini = linea.find("http")
                if ini >= 0:
                    return linea[ini:].strip().split()[0]
        return None

    proc = _run([binary, "-a", "-f", remote_path])
    link = _buscar(proc)
    if not link and proc.returncode != 0:
        # Si ya existía el export, `-a` da error: recuperamos el enlace actual.
        proc2 = _run([binary, remote_path])
        link = _buscar(proc2)
    if not link:
        raise MegaCmdUnavailable(
            "mega-export no devolvió enlace para "
            f"{remote_path!r} (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()[:200]}"
        )
    return link


def dump_tree(timeout: int | None = None) -> str:
    """Ejecuta `mega-ls -R -l` y devuelve el volcado en texto (canon)."""
    binary = _which([settings.mega_ls_bin, "mega-ls"])
    if binary is None:
        raise MegaCmdUnavailable(probe().error or "mega-ls no encontrado")
    try:
        proc = subprocess.run(
            [binary, "-R", "-l", "/"],
            capture_output=True,
            text=True,
            timeout=timeout or settings.mega_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise MegaCmdUnavailable(f"mega-ls agotó el tiempo ({settings.mega_timeout_s}s)") from exc
    except OSError as exc:
        raise MegaCmdUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        raise MegaCmdUnavailable(
            f"mega-ls falló (rc={proc.returncode}): {proc.stderr.strip()[:400]}"
        )
    return proc.stdout
