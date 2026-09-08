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

    # ── API ────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 7331
    cors_origins: str = "http://localhost:7330,http://127.0.0.1:7330"

    # ── MEGAcmd ────────────────────────────────────────────
    mega_ls_bin: str = "mega-ls"
    megacmd_bin: str = "megacmd"
    mega_export_bin: str = "mega-export"
    mega_timeout_s: int = 180

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
    igdb_token_url: str = "https://id.twitch.tv/oauth2/token"
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
