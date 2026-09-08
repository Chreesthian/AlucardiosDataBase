"""Esquemas Pydantic de la API (v2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── snapshots / meta ─────────────────────────────────────────
class SnapshotOut(OrmModel):
    id: int
    account: str | None
    tool: str | None
    generated_at: str | None
    source_kind: str
    source_path: str | None
    content_sha256: str | None
    ingested_at: datetime
    file_count: int
    folder_count: int
    total_size: int


class BucketOut(BaseModel):
    letter: str
    titles: int
    size_bytes: int


class MetaOut(BaseModel):
    snapshot: SnapshotOut | None
    titles: int
    files: int
    folders: int
    bytes: int
    covers: int = 0
    buckets: list[BucketOut]


# ── títulos ──────────────────────────────────────────────────
class TitleSummary(OrmModel):
    slug: str
    name: str
    letter: str
    size_bytes: int
    file_count: int
    folder_count: int
    base_count: int
    update_count: int
    dlc_count: int
    other_count: int
    ext_json: str | None
    igdb_slug: str | None
    igdb_cover: str | None


class TitleListOut(BaseModel):
    items: list[TitleSummary]
    total: int
    offset: int
    limit: int


# ── detalle de título ────────────────────────────────────────
class FileOut(BaseModel):
    name: str
    size: int
    ext: str | None
    path: str  # relativa al título
    full_path: str | None = None  # ruta absoluta del nodo (para descarga MEGA)


class VersionOut(BaseModel):
    id: int
    name: str
    label: str  # base | update | dlc | other | carpeta
    size_bytes: int
    file_count: int
    folder_count: int
    full_path: str | None = None  # ruta MEGA del nodo carpeta (descarga)
    files: list[FileOut]


class TitleDetailOut(BaseModel):
    slug: str
    name: str
    name_norm: str
    letter: str
    size_bytes: int
    file_count: int
    folder_count: int
    base_count: int
    update_count: int
    dlc_count: int
    formats: list[str]
    igdb_slug: str | None
    igdb_cover: str | None
    ficha: dict | None = None  # ficha IGDB completa (ficha_v 2), si está enriquecido
    versions: list[VersionOut]
    remaining_files: list[FileOut]  # archivos directos del título (sin versión)


# ── sync ─────────────────────────────────────────────────────
class SyncStatusOut(BaseModel):
    last_snapshot: SnapshotOut | None
    configured_dump: str
    dump_exists: bool
    megacmd_available: bool
    megacmd_binary: str | None
    megacmd_error: str | None
    ultimo_escaneo: dict | None = None  # resumen del último diff aplicado


class SyncRunOut(BaseModel):
    ok: bool
    snapshot: SnapshotOut | None = None
    resumen: dict | None = None
    error: str | None = None
