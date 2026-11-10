"""Configuración central del backend.

Sigue el patrón de configuración pydantic-settings de un proyecto anterior.
Todas las variables se leen con prefijo `ALUCARD_` desde el entorno o un `.env`.
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def backend_dir() -> Path:
    """backend/ (este paquete vive en backend/app)."""
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    """Raíz del repo (padre de backend/)."""
    return backend_dir().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALUCARD_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AlucardiosDataBase API"
    debug: bool = True

    # ── Datos ──────────────────────────────────────────────
    dump_path: Path | None = None
    database_url: str | None = None
    db_path: Path | None = None

    # ── Colección RETRO (sección aparte, F6) ───────────────
    # Las ROMs retro viven en OTRO in-share (`INSHARE ...:ORTIK 90`, montado por
    # otra cuenta del pool) y se indexan en SU PROPIA BD: mezclarlas con el
    # catálogo Switch contaminaría `/api/meta`, los buckets y "Novedades" (los
    # sectores de un volcado no son los del otro, cada uno rota por su cuenta).
    # Por defecto: `data/mega_retro_contenido_MEGAcmd.txt` + `data/retro.db`.
    # El volcado vive en `data/` (no en la raíz) para que el bind-mount de Docker
    # monte un DIRECTORIO existente y nunca cree un directorio con su nombre.
    retro_dump_path: Path | None = None
    retro_database_url: str | None = None
    retro_db_path: Path | None = None

    # ── API ────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 7331
    cors_origins: str = "http://localhost:7330,http://127.0.0.1:7330"

    # ── MEGAcmd ────────────────────────────────────────────
    mega_ls_bin: str = "mega-ls"
    megacmd_bin: str = "megacmd"
    mega_export_bin: str = "mega-export"
    mega_timeout_s: int = 180

    # ── Actualización guiada desde la interfaz ─────────────
    # El paquete de escritorio ejecuta el backend en el mismo equipo que MEGAcmd;
    # estas rutas permiten que el binario final las resuelva sin tocar el repo.
    # Los secretos viven fuera de la BD y fuera de git (ver mega_setup.py).
    mega_bin_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("MEGA_BIN", "ALUCARD_MEGA_BIN"),
    )
    mega_cuentas_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ALUCARD_MEGA_CUENTAS",
            "ALUCARD_MEGA_CUENTAS_PATH",
        ),
    )
    mega_env_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ALUCARD_MEGA_ENV",
            "ALUCARD_MEGA_ENV_PATH",
        ),
    )
    mega_scripts_dir: Path | None = None
    mega_python_bin: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALUCARD_PYTHON", "ALUCARD_MEGA_PYTHON"),
    )
    mega_update_timeout_s: int = 7200
    actualizacion_estado_path: Path | None = None
    actualizacion_log_path: Path | None = None

    # ── Puente host para la UI Docker ─────────────────────
    # El contenedor no puede usar MEGAcmd; si esta URL está definida, la API le
    # delega la actualización a un agente que corre en el host. El token protege
    # el puerto del agente y se comparte por un fichero dentro de `data/`.
    update_agent_url: str | None = None
    update_agent_token_path: Path | None = None
    update_agent_socket_path: Path | None = None
    update_agent_timeout_s: float = 15.0

    # ── Frescura del volcado (pipeline de actualización) ────
    # Edad máxima (horas) que puede tener el volcado canónico antes de que el
    # vigía `app.sync --watch` lo considere OBSOLETO y falle a propósito: si la
    # automatización del refresco (scripts/autovolcado.sh, cron cada 6 h) se
    # rompe, la BD se queda congelada sin avisar. 0 desactiva el guard.
    sync_max_edad_horas: int = 26
    # Fracción mínima de archivos que debe conservar un volcado para aplicarse
    # (protege de escrituras a medias y de bajadas masivas no intencionadas).
    sync_min_fraccion: float = 0.5
    # Fracción mínima de TÍTULOS (carpetas de juego) que debe conservar un
    # volcado. Un share re-compartido a medias, o una cuenta que ve menos
    # sectores, puede traer muchos archivos (pasa el guard anterior) y aun así
    # dejar el catálogo mutilado: esto lo corta antes del diff. 0 lo desactiva.
    sync_min_titulos_fraccion: float = 0.9

    # ── Pre-vuelo de rotación MEGA (host) ──────────────────
    # `scripts/verificar_rotacion.py` (host, vía `make volcado`) deja aquí su
    # veredicto para que la API lo publique en `GET /api/sync/cuentas` y la UI
    # pueda avisar cuando las credenciales de la semana montan OTRA biblioteca.
    # Por defecto, junto a la BD (`data/estado_cuentas.json`); en Docker se monta
    # el `data/` del host en solo lectura y se apunta con esta variable.
    estado_cuentas_path: Path | None = None

    # ── IGDB / GamesDb (metadatos, fase F4) ────────────────
    # Credenciales IGDB (Twitch) con los mismos nombres que el proyecto anterior
    # (IGDB_CLIENT_ID / IGDB_CLIENT_SECRET en .env) o con prefijo ALUCARD_.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    http_timeout: float = 15.0
    igdb_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IGDB_CLIENT_ID", "ALUCARD_IGDB_CLIENT_ID"),
    )
    igdb_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IGDB_CLIENT_SECRET", "ALUCARD_IGDB_CLIENT_SECRET"),
    )
    igdb_base_url: str = "https://api.igdb.com/v4"
    igdb_token_url: str = (
        "https://id.twitch.tv/oauth2/token"  # noqa: S105 — URL OAuth, no una credencial
    )
    igdb_throttle_seconds: float = 0.3

    # ── Derivados ──────────────────────────────────────────
    @property
    def resolved_dump(self) -> Path:
        if self.dump_path is not None:
            p = Path(self.dump_path)
            return p if p.is_absolute() else (project_root() / p).resolve()
        return project_root() / "mega_cuenta_contenido_MEGAcmd.txt"

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            p = Path(self.db_path)
            return p if p.is_absolute() else (project_root() / p).resolve()
        return project_root() / "data" / "alucard.db"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db = self.resolved_db_path
        db.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db}"

    # ── Derivados de la colección retro ────────────────────
    @property
    def resolved_retro_dump(self) -> Path:
        if self.retro_dump_path is not None:
            p = Path(self.retro_dump_path)
            return p if p.is_absolute() else (project_root() / p).resolve()
        return project_root() / "data" / "mega_retro_contenido_MEGAcmd.txt"

    @property
    def resolved_retro_db_path(self) -> Path:
        if self.retro_db_path is not None:
            p = Path(self.retro_db_path)
            return p if p.is_absolute() else (project_root() / p).resolve()
        return project_root() / "data" / "retro.db"

    @property
    def resolved_retro_database_url(self) -> str:
        if self.retro_database_url:
            return self.retro_database_url
        db = self.resolved_retro_db_path
        db.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db}"

    @property
    def resolved_estado_cuentas(self) -> Path:
        """Informe del pre-vuelo de rotación (por defecto, junto a la BD)."""
        if self.estado_cuentas_path is not None:
            p = Path(self.estado_cuentas_path)
            return p if p.is_absolute() else (project_root() / p).resolve()
        return self.resolved_db_path.parent / "estado_cuentas.json"

    # ── Derivados de la actualización guiada ──────────────
    @staticmethod
    def _ruta_config(valor: Path | None, defecto: Path) -> Path:
        if valor is None:
            return defecto.expanduser()
        p = Path(valor).expanduser()
        return p if p.is_absolute() else (project_root() / p).resolve()

    @property
    def resolved_mega_cuentas(self) -> Path:
        """Pool de las tres cuentas, fuera del repo y de la BD."""
        return self._ruta_config(
            self.mega_cuentas_path,
            Path.home() / ".config" / "alucard" / "mega_cuentas.txt",
        )

    @property
    def resolved_mega_env(self) -> Path:
        """Credencial preferida (la que MEGAcmd intenta primero)."""
        return self._ruta_config(
            self.mega_env_path,
            Path.home() / ".config" / "alucard" / "mega.env",
        )

    @property
    def resolved_mega_scripts(self) -> Path:
        """Scripts host reutilizados por la actualización (no se reimplementan)."""
        return self._ruta_config(self.mega_scripts_dir, project_root() / "scripts")

    @property
    def resolved_mega_bin(self) -> Path:
        """Directorio de MEGAcmd; admite binario suelto o MEGA_BIN del host."""
        if self.mega_bin_dir is not None:
            p = Path(self.mega_bin_dir).expanduser()
            return p.parent if p.is_file() else p
        if os.environ.get("MEGA_BIN"):
            p = Path(os.environ["MEGA_BIN"]).expanduser()
            return p.parent if p.is_file() else p
        candidatos: list[Path] = []
        for nombre in ("mega-cmd", "mega-ls", "mega-cmd.exe", "mega-ls.exe"):
            encontrado = shutil.which(nombre)
            if encontrado:
                candidatos.append(Path(encontrado).resolve().parent)
        candidatos += [
            Path.home() / "opt" / "megacmd" / "usr" / "bin",
            Path("/opt/megacmd/usr/bin"),
            Path("/usr/local/bin"),
        ]
        for candidato in candidatos:
            if any(
                (candidato / nombre).is_file()
                for nombre in ("mega-cmd", "mega-cmd.exe", "mega-ls", "mega-ls.exe")
            ):
                return candidato
        return candidatos[0] if candidatos else Path("/nonexistent")

    @property
    def resolved_mega_python(self) -> str:
        """Intérprete que ejecuta los scripts; empaquetable con ALUCARD_PYTHON."""
        return self.mega_python_bin or sys.executable

    @property
    def resolved_actualizacion_estado(self) -> Path:
        return self._ruta_config(
            self.actualizacion_estado_path,
            self.resolved_db_path.parent / "actualizacion_estado.json",
        )

    @property
    def resolved_actualizacion_log(self) -> Path:
        return self._ruta_config(
            self.actualizacion_log_path,
            self.resolved_db_path.parent / "actualizacion.log",
        )

    @property
    def resolved_update_agent_token(self) -> Path:
        """Token compartido con el agente host (no es una credencial MEGA)."""
        return self._ruta_config(
            self.update_agent_token_path,
            self.resolved_db_path.parent / "update_agent.token",
        )

    @property
    def resolved_update_agent_socket(self) -> Path:
        """Socket Unix del agente; evita abrir un puerto TCP en el host."""
        return self._ruta_config(
            self.update_agent_socket_path,
            self.resolved_db_path.parent / "update_agent.sock",
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
