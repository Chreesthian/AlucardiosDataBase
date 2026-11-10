"""Configuración local de las cuentas MEGA y actualización del catálogo.

La pantalla de mantenimiento no reimplementa MEGA ni el diff del catálogo:
guarda las tres cuentas en un fichero privado fuera del repo y orquesta los
mismos scripts que usa el host (`verificar_rotacion.py` → `refrescar_volcado.py`)
para terminar aplicando `app.sync.refresh` sobre la BD local.

Reglas de seguridad:
- las contraseñas solo viven en el fichero del pool (chmod 600), nunca en la BD,
  en la API de estado ni en los logs;
- la actualización se ejecuta en el equipo donde está MEGAcmd. Si la app corre
  en un contenedor sin MEGAcmd, el servicio se declara no disponible y no escribe
  credenciales;
- un fallo del pre-vuelo o del volcado deja la BD intacta.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.engine import Engine

from .config import Settings
from .parser import parse_file
from .safefs import atomic_write_text
from .sync import refresh

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_SEPARADOR = re.compile(r"[\t;,=]|\s+")
Progreso = Callable[[str, str], None]


class MegaSetupError(RuntimeError):
    """Error de configuración/actualización con un mensaje apto para la UI."""


class MegaSetupUnavailable(MegaSetupError):
    """La instalación no puede ejecutar MEGAcmd (p. ej. backend en contenedor)."""


class MegaSetupInvalid(MegaSetupError):
    """Las cuentas o la petición no son válidas."""


class MegaUpdateBusy(MegaSetupError):
    """Ya hay una actualización en curso."""


class MegaUpdateFailed(MegaSetupError):
    """La actualización empezó pero no pudo completarse."""


@dataclass(frozen=True)
class MegaCuenta:
    email: str
    password: str


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalizar_cuentas(cuentas: list[MegaCuenta]) -> list[MegaCuenta]:
    """Valida y normaliza exactamente las tres cuentas de la rotación."""
    if len(cuentas) != 3:
        raise MegaSetupInvalid("Introduce exactamente tres cuentas MEGA.")
    salida: list[MegaCuenta] = []
    vistos: set[str] = set()
    for cuenta in cuentas:
        email = (cuenta.email or "").strip()
        password = cuenta.password or ""
        if not _RE_EMAIL.fullmatch(email):
            raise MegaSetupInvalid(f"El correo no es válido: {email or '(vacío)'}.")
        if not password:
            raise MegaSetupInvalid(f"Falta la contraseña de {email}.")
        if len(password) > 256 or any(c in password for c in "\r\n\t"):
            raise MegaSetupInvalid(
                f"La contraseña de {email} no puede contener saltos de línea ni tabuladores."
            )
        clave = email.lower()
        if clave in vistos:
            raise MegaSetupInvalid("Las tres cuentas deben ser distintas.")
        vistos.add(clave)
        salida.append(MegaCuenta(email=email, password=password))
    return salida


def _linea_cuenta(linea: str) -> tuple[str, str] | None:
    """`email<sep>password` → (email, password); ignora comentarios y ruido."""
    texto = linea.strip()
    if not texto or texto.startswith("#"):
        return None
    partes = [p for p in _RE_SEPARADOR.split(texto, maxsplit=1) if p]
    if len(partes) != 2:
        return None
    email, password = partes[0].strip(), partes[1].strip()
    if not email or not password:
        return None
    return email, password


class MegaCredentialStore:
    """Pool privado de cuentas + credencial preferida, fuera del repo."""

    def __init__(self, pool_path: Path, preferred_path: Path) -> None:
        self.pool_path = Path(pool_path)
        self.preferred_path = Path(preferred_path)

    def emails(self) -> list[str]:
        """Solo correos: la API de estado nunca devuelve contraseñas."""
        return [cuenta.email for cuenta in self.load()]

    def load(self) -> list[MegaCuenta]:
        """Uso interno del runner; nunca se serializa en una respuesta."""
        if not self.pool_path.is_file():
            return []
        try:
            texto = self.pool_path.read_text(encoding="utf-8")
        except OSError:
            return []
        salida: list[MegaCuenta] = []
        for linea in texto.splitlines():
            par = _linea_cuenta(linea)
            if par:
                salida.append(MegaCuenta(email=par[0], password=par[1]))
        return salida

    def has_credentials(self) -> bool:
        return bool(self.emails())

    def preferred_email(self) -> str | None:
        """Correo de la credencial preferida, sin leer la contraseña."""
        if not self.preferred_path.is_file():
            return None
        try:
            texto = self.preferred_path.read_text(encoding="utf-8")
        except OSError:
            return None
        for linea in texto.splitlines():
            clave, separador, valor = linea.partition("=")
            if separador and clave.strip() == "MEGA_EMAIL" and valor.strip():
                return valor.strip().strip('"').strip("'")
        return None

    def save(self, cuentas: list[MegaCuenta]) -> None:
        """Guarda el pool y deja la primera cuenta como preferida.

        El formato es el que ya leen `mega_session.sh`, `verificar_rotacion.py`
        y `explorar_cuentas_mega.py`: una cuenta por línea separada por tabulador.
        """
        cuentas = normalizar_cuentas(cuentas)
        pool = "# Cuentas MEGA de la rotación semanal (fichero privado).\n"
        pool += "".join(f"{c.email}\t{c.password}\n" for c in cuentas)
        self._write_private(self.pool_path, pool)
        primera = cuentas[0]
        self._write_private(
            self.preferred_path,
            f"MEGA_EMAIL={primera.email}\nMEGA_PASSWORD={primera.password}\n",
        )

    @staticmethod
    def _write_private(path: Path, texto: str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        umask_previo = os.umask(0o077)
        try:
            atomic_write_text(path, texto)
        finally:
            os.umask(umask_previo)
        with suppress(OSError):
            # Windows / FS sin permisos POSIX: el directorio del usuario manda.
            path.chmod(0o600)


class MegaRunner(Protocol):
    """Contrato mínimo para actualizar; los tests inyectan un runner falso."""

    def available(self) -> tuple[bool, str | None]: ...

    def run(self, *, progress: Progreso, secrets: list[str]) -> dict: ...


class MegaUpdateManager:
    """Ejecuta una actualización como máximo y publica su estado sin secretos."""

    def __init__(self, store: MegaCredentialStore, runner: MegaRunner, state_path: Path) -> None:
        self.store = store
        self.runner = runner
        self.state_path = Path(state_path)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = self._load_state()

    @staticmethod
    def _estado_inicial() -> dict:
        return {
            "estado": "inactivo",
            "fase": None,
            "mensaje": None,
            "inicio": None,
            "fin": None,
            "cuenta": None,
            "resumen": None,
            "error": None,
        }

    def _load_state(self) -> dict:
        estado = self._estado_inicial()
        if self.state_path.is_file():
            try:
                datos = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                datos = None
            if isinstance(datos, dict):
                estado.update({clave: datos.get(clave) for clave in estado})
        if estado["estado"] == "en_curso":
            estado.update(
                estado="error",
                fase="interrumpida",
                mensaje="La actualización anterior se interrumpió. Vuelve a intentarlo.",
                error="La actualización anterior se interrumpió. Vuelve a intentarlo.",
                fin=_ahora(),
            )
            self._write_state(estado)
        return estado

    def _write_state(self, estado: dict) -> None:
        # El estado no contiene contraseñas: solo fase, cuenta y resumen del diff.
        atomic_write_text(
            self.state_path,
            json.dumps(estado, ensure_ascii=False, indent=1) + "\n",
        )

    def status(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._state, ensure_ascii=False))

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise MegaUpdateBusy("Ya hay una actualización en curso.")
            self._state = {
                **self._estado_inicial(),
                "estado": "en_curso",
                "fase": "guardando",
                "mensaje": "Guardando las cuentas y preparando la actualización…",
                "inicio": _ahora(),
            }
            self._write_state(self._state)
            self._thread = threading.Thread(
                target=self._run,
                name="alucard-mega-update",
                daemon=True,
            )
            self._thread.start()

    def _progress(self, fase: str, mensaje: str) -> None:
        with self._lock:
            if self._state.get("estado") != "en_curso":
                return
            self._state.update(fase=fase, mensaje=mensaje)
            self._write_state(self._state)

    def _fail(self, mensaje: str) -> None:
        with self._lock:
            self._state.update(
                estado="error",
                fase=self._state.get("fase"),
                mensaje=mensaje,
                error=mensaje,
                fin=_ahora(),
            )
            self._write_state(self._state)

    def _run(self) -> None:
        try:
            secretos = [c.password for c in self.store.load()]
            resultado = self.runner.run(progress=self._progress, secrets=secretos)
        except MegaUpdateFailed as exc:
            self._fail(str(exc))
        except Exception:  # noqa: BLE001 - un fallo inesperado no filtra secretos
            self._fail(
                "La actualización no pudo completarse. La base de datos no se ha "
                "modificado. Revisa el registro local e inténtalo de nuevo."
            )
        else:
            with self._lock:
                self._state.update(
                    estado="ok",
                    fase="listo",
                    mensaje="Biblioteca actualizada.",
                    fin=_ahora(),
                    cuenta=resultado.get("cuenta"),
                    resumen=resultado.get("resumen"),
                    error=None,
                )
                self._write_state(self._state)
        finally:
            with self._lock:
                self._thread = None


def _leer_json(path: Path) -> dict:
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


class HostMegaRunner:
    """Orquesta los scripts host existentes y aplica el diff en esta BD."""

    def __init__(self, cfg: Settings, engine: Engine) -> None:
        self.cfg = cfg
        self.engine = engine

    def _mega_bin_ok(self) -> bool:
        binario = self.cfg.resolved_mega_bin
        return any(
            (binario / nombre).is_file()
            for nombre in ("mega-cmd", "mega-cmd.exe", "mega-ls", "mega-ls.exe")
        )

    def available(self) -> tuple[bool, str | None]:
        scripts = self.cfg.resolved_mega_scripts
        necesarios = ("verificar_rotacion.py", "refrescar_volcado.py")
        faltan = [nombre for nombre in necesarios if not (scripts / nombre).is_file()]
        if faltan:
            return False, (
                "Esta instalación no incluye los scripts de actualización de MEGA."
            )
        if not (scripts.parent / "build_megacmd_dump.py").is_file():
            return False, "Falta el generador del volcado de MEGA en esta instalación."
        if not self._mega_bin_ok():
            return False, (
                "MEGAcmd no está disponible en este equipo. La actualización "
                "automática se ejecuta desde la aplicación de escritorio."
            )
        return True, None

    def _env(self, scripts: Path) -> dict[str, str]:
        root = scripts.parent
        backend = Path(__file__).resolve().parents[1]
        binario = self.cfg.resolved_mega_bin
        env = os.environ.copy()
        # No heredar credenciales viejas: la fuente de verdad es el pool privado.
        env.pop("MEGA_EMAIL", None)
        env.pop("MEGA_PASSWORD", None)
        env["MEGA_BIN"] = str(binario)
        env["ALUCARD_MEGA_CUENTAS"] = str(self.cfg.resolved_mega_cuentas)
        env["ALUCARD_MEGA_ENV"] = str(self.cfg.resolved_mega_env)
        env["PATH"] = os.pathsep.join([str(binario), env.get("PATH", "")])
        env["PYTHONPATH"] = os.pathsep.join(
            [str(root), str(backend), str(scripts), env.get("PYTHONPATH", "")]
        )
        return env

    def _log(self, texto: str, *, secrets: list[str]) -> None:
        for secreto in secrets:
            if secreto:
                texto = texto.replace(secreto, "***")
        if not texto:
            return
        path = self.cfg.resolved_actualizacion_log
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for linea in texto.splitlines():
                fh.write(f"[{_ahora()}] {linea}\n")
        with suppress(OSError):
            path.chmod(0o600)

    def _run(
        self,
        cmd: list[str],
        *,
        env: dict[str, str],
        cwd: Path,
        etiqueta: str,
        secrets: list[str],
    ) -> int:
        self._log(f"── {etiqueta} ──", secrets=secrets)
        try:
            proc = subprocess.run(  # noqa: S603 - comandos construidos con rutas resueltas
                cmd,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.cfg.mega_update_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MegaUpdateFailed(
                f"{etiqueta}: se agotó el tiempo de espera. La base de datos no se ha "
                "modificado."
            ) from exc
        except OSError as exc:
            raise MegaUpdateFailed(
                f"{etiqueta}: no se pudo ejecutar el proceso de actualización."
            ) from exc
        self._log(proc.stdout or "", secrets=secrets)
        self._log(proc.stderr or "", secrets=secrets)
        return proc.returncode


    def run(self, *, progress: Progreso, secrets: list[str]) -> dict:
        scripts = self.cfg.resolved_mega_scripts
        root = scripts.parent
        env = self._env(scripts)
        python = self.cfg.resolved_mega_python
        estado_path = self.cfg.resolved_estado_cuentas
        estado_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            estado_path.unlink(missing_ok=True)

        progress("verificando", "Comprobando las tres cuentas y la biblioteca…")
        preflight = [
            python,
            str(scripts / "verificar_rotacion.py"),
            "--elegir-cuenta",
            "--login-preferida",
            "--cuentas",
            str(self.cfg.resolved_mega_cuentas),
            "--volcado",
            str(self.cfg.resolved_dump),
            "--json",
            str(estado_path),
            "--mega-bin",
            str(self.cfg.resolved_mega_bin),
            "--guardar-elegida",
            "--env-destino",
            str(self.cfg.resolved_mega_env),
            "--quiet",
        ]
        rc = self._run(
            preflight,
            env=env,
            cwd=root,
            etiqueta="Comprobando cuentas MEGA",
            secrets=secrets,
        )
        informe = _leer_json(estado_path)
        if rc == 4:
            raise MegaUpdateFailed(
                "No se pudo iniciar sesión con ninguna de las tres cuentas. "
                "Revisa los correos y las contraseñas."
            )
        if rc == 8:
            veredicto = informe.get("veredicto")
            detalle = f" {veredicto}" if isinstance(veredicto, str) and veredicto else ""
            raise MegaUpdateFailed(
                "Las cuentas no ven la biblioteca de MEGA. No se ha modificado la "
                f"base de datos.{detalle}"
            )
        if rc != 0:
            raise MegaUpdateFailed(
                f"No se pudo comprobar la biblioteca (código {rc}). "
                "La base de datos no se ha modificado."
            )

        progress("volcando", "Descargando el catálogo actualizado desde MEGA…")
        refresco = [
            python,
            str(scripts / "refrescar_volcado.py"),
            "--mega-bin",
            str(self.cfg.resolved_mega_bin),
            "--out",
            str(self.cfg.resolved_dump),
            "--min-titulos-fraccion",
            str(self.cfg.sync_min_titulos_fraccion),
        ]
        rc = self._run(
            refresco,
            env=env,
            cwd=root,
            etiqueta="Actualizando el volcado MEGA",
            secrets=secrets,
        )
        if rc != 0:
            raise MegaUpdateFailed(
                "El volcado nuevo no conserva la biblioteca. No se ha modificado "
                "la base de datos."
            )

        progress("sincronizando", "Aplicando los cambios a la base de datos…")
        try:
            parsed = parse_file(self.cfg.resolved_dump)
            resumen = refresh(
                self.engine,
                parsed,
                kind="dump",
                source_path=str(self.cfg.resolved_dump),
                min_fraccion=self.cfg.sync_min_fraccion,
                min_titulos_fraccion=self.cfg.sync_min_titulos_fraccion,
            )
        except Exception as exc:  # mensaje para la UI, sin secretos
            raise MegaUpdateFailed(
                "El volcado se actualizó, pero la base de datos no pudo aplicar los "
                f"cambios: {exc}"
            ) from exc

        return {
            "cuenta": informe.get("cuenta") or informe.get("elegida"),
            "resumen": resumen,
            "biblioteca": informe.get("biblioteca"),
        }


class MegaSetupService:
    """Fachada pequeña para la API: estado, guardado y arranque del job."""

    def __init__(
        self,
        cfg: Settings,
        engine: Engine,
        runner: MegaRunner | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = MegaCredentialStore(
            cfg.resolved_mega_cuentas,
            cfg.resolved_mega_env,
        )
        self.runner = runner or HostMegaRunner(cfg, engine)
        self.manager = MegaUpdateManager(
            self.store,
            self.runner,
            cfg.resolved_actualizacion_estado,
        )

    def status(self) -> dict:
        disponible, motivo = self.runner.available()
        emails = self.store.emails()
        preferida = self.store.preferred_email()
        if preferida not in emails:
            preferida = emails[0] if emails else None
        return {
            "disponible": disponible,
            "motivo": motivo,
            "cuentas": [
                {
                    "email": email,
                    "password_guardada": True,
                    "preferida": email == preferida,
                }
                for email in emails
            ],
            "actualizacion": self.manager.status(),
        }

    def start(self, cuentas: list[MegaCuenta] | None = None) -> dict:
        disponible, motivo = self.runner.available()
        if not disponible:
            raise MegaSetupUnavailable(
                motivo or "La actualización de MEGA no está disponible en este equipo."
            )
        if cuentas is not None:
            try:
                self.store.save(cuentas)
            except OSError as exc:
                raise MegaSetupInvalid(
                    "No se pudieron guardar las cuentas en este equipo."
                ) from exc
        elif not self.store.has_credentials():
            raise MegaSetupInvalid("Introduce las tres cuentas MEGA.")
        self.manager.start()
        return self.status()
