"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped`).

Diseño:
- `Snapshot`: un volcado ingerido (canon inmutables → historial de sincronización).
- `Node`: árbol genérico sector→bucket→título→versión→archivo con agregados
  recursivos (`total_size`, `total_files`, `total_folders`) materializados.
- `Title`: vista semántica de "juego" (carpeta de profundidad 2 en un bucket)
  con resumen de versiones, extensiones y huecos reservados para IGDB (F4).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Cabecera del volcado
    account: Mapped[str | None] = mapped_column(String(255))
    tool: Mapped[str | None] = mapped_column(String(255))
    generated_at: Mapped[str | None] = mapped_column(String(64))
    # Origen
    source_kind: Mapped[str] = mapped_column(String(16), default="dump")  # dump|megacmd
    source_path: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    # Totales globales
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    folder_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path", name="uq_nodes_snapshot_path"),
        Index("ix_nodes_snapshot_role", "snapshot_id", "role"),
        Index("ix_nodes_snapshot_parent", "snapshot_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)  # relativa al sector, p. ej. `-- A/Game/`
    name: Mapped[str] = mapped_column(Text)
    depth: Mapped[int] = mapped_column(Integer, default=0)  # 0 = raíz de sector
    kind: Mapped[str] = mapped_column(String(8))  # folder | file
    role: Mapped[str] = mapped_column(String(16), default="")  # root|bucket|title|version|…
    ext: Mapped[str | None] = mapped_column(String(16))
    size: Mapped[int] = mapped_column(BigInteger, default=0)  # tamaño directo (solo hojas)
    # Agregados de subárbol (folders)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_folders: Mapped[int] = mapped_column(Integer, default=0)
    node_order: Mapped[int] = mapped_column(Integer, default=0)


class DownloadLink(Base):
    """Índice de rutas → enlace público de descarga (MEGA).

    Se puebla en lote (`python -m app.indexar_descargas`) o bajo demanda
    (primer clic en /api/download). `estado`: pendiente | ok | error.
    """

    __tablename__ = "downloads"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path", name="uq_downloads_snapshot_path"),
        Index("ix_downloads_snapshot_estado", "snapshot_id", "estado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    nivel: Mapped[str] = mapped_column(String(16))  # archivo | carpeta
    link: Mapped[str | None] = mapped_column(Text)
    metodo: Mapped[str] = mapped_column(String(32), default="mega_export")  # mega_export | share
    estado: Mapped[str] = mapped_column(String(16), default="pendiente")  # pendiente | ok | error
    error: Mapped[str | None] = mapped_column(Text)
    generado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncLog(Base):
    """Registro de cada escaneo incremental (añadidos/borrados/cambiados)."""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    kind: Mapped[str] = mapped_column(String(16), default="dump")  # dump|megacmd
    source_path: Mapped[str | None] = mapped_column(Text)
    added_files: Mapped[int] = mapped_column(Integer, default=0)
    removed_files: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    added_folders: Mapped[int] = mapped_column(Integer, default=0)
    removed_folders: Mapped[int] = mapped_column(Integer, default=0)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_folders: Mapped[int] = mapped_column(Integer, default=0)


class Title(Base):
    __tablename__ = "titles"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "slug", name="uq_titles_snapshot_slug"),
        Index("ix_titles_snapshot_norm", "snapshot_id", "name_norm"),
        Index("ix_titles_snapshot_bucket", "snapshot_id", "letter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text)  # minúsculas sin acentos (búsqueda)
    letter: Mapped[str] = mapped_column(String(2))  # '#', 'A'… 'Z'
    # Agregados del título
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    folder_count: Mapped[int] = mapped_column(Integer, default=0)
    # Versiones directas
    base_count: Mapped[int] = mapped_column(Integer, default=0)
    update_count: Mapped[int] = mapped_column(Integer, default=0)
    dlc_count: Mapped[int] = mapped_column(Integer, default=0)
    other_count: Mapped[int] = mapped_column(Integer, default=0)
    ext_json: Mapped[str | None] = mapped_column(Text)  # {"rar": n, "nsp": n}
    # Metadatos IGDB (F4)
    igdb_slug: Mapped[str | None] = mapped_column(String(255))
    igdb_cover: Mapped[str | None] = mapped_column(Text)
    igdb_json: Mapped[str | None] = mapped_column(Text)


class Novedad(Base):
    """Evento de la sección "Novedades" (historial append-only).

    Se registra en cada escaneo incremental (`app.sync`) a partir del diff de
    rutas: un título nuevo produce un evento `juego_nuevo`; los archivos nuevos
    dentro de un título ya existente producen `update_nuevo`, `dlc_nuevo` o
    `contenido_nuevo` según la carpeta de versión (`U-PD…`, `D-LC…`, …).

    Los eventos se conservan aunque el título desaparezca de la biblioteca
    (por eso se duplican `slug`/`name`/`letter` y no hay FK a `titles`).
    """

    __tablename__ = "novedades"
    __table_args__ = (
        Index("ix_novedades_detectada", "detectada_en"),
        Index("ix_novedades_tipo", "tipo"),
        Index("ix_novedades_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(Text)
    letter: Mapped[str] = mapped_column(String(2), default="#")
    tipo: Mapped[str] = mapped_column(
        String(24)
    )  # juego_nuevo|update_nuevo|dlc_nuevo|contenido_nuevo
    version: Mapped[str | None] = mapped_column(Text)  # carpeta de versión (p. ej. "U-PD 1.3.0")
    archivos: Mapped[int] = mapped_column(Integer, default=0)  # archivos nuevos del evento
    bytes_nuevos: Mapped[int] = mapped_column(BigInteger, default=0)
    detalle_json: Mapped[str | None] = mapped_column(Text)  # rutas nuevas (relativas al título)
    igdb_cover: Mapped[str | None] = mapped_column(Text)  # carátula en el momento del evento
    detectada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
