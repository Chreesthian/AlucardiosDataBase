"""Configuración central del backend.

Sigue el patrón de configuración pydantic-settings de un proyecto anterior.
Todas las variables se leen con prefijo `ALUCARD_` desde el entorno o un `.env`.
"""

from __future__ import annotations

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
