"""Esquemas Pydantic de la API (v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from .plataformas import de_letra


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── plataformas (sistemas) ───────────────────────────────────
class PlataformaOut(BaseModel):
    """Plataforma/sistema OFICIAL del juego (no el código del volcado).

    `letter` sigue siendo la identidad del bucket en el volcado (la letra A-Z en
    Switch, el sistema `ARC N-64` en retro); esto es cómo se llama de verdad esa
    plataforma. Los datos vienen del catálogo `/v4/platforms` de IGDB
    (`app.plataformas`) y `conocido=False` avisa de un código del volcado que
    todavía no está en el catálogo: se publica tal cual, nunca se inventa.
    """

    model_config = ConfigDict(from_attributes=True)

    clave: str  # identificador estable (slug) para URLs y claves de UI
    nombre: str  # nombre OFICIAL
    corto: str  # etiqueta corta para chips y badges (UI densa)
    igdb_id: int | None = None
    igdb_slug: str | None = None
    generacion: int | None = None
    familia: str | None = None
    conocido: bool = True


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


class _ConPlataforma(BaseModel):
    """Mixin de los payloads que identifican un bucket: añade su plataforma oficial.

    `letter` es la identidad del bucket en el volcado (letra A-Z en Switch,
    sistema `ARC N-64` en retro); `plataforma` es ese mismo bucket traducido al
    nombre OFICIAL (`app.plataformas`). Se completa aquí, en un solo sitio, para
    que ningún endpoint pueda publicar uno sin el otro.
    """

    letter: str
    plataforma: PlataformaOut | None = None

    @model_validator(mode="after")
    def _completar_plataforma(self) -> Self:
        if self.plataforma is None:
            self.plataforma = PlataformaOut.model_validate(de_letra(self.letter))
        return self


class BucketOut(_ConPlataforma):
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
class TitleSummary(_ConPlataforma, OrmModel):
    slug: str
    name: str
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
    # Identidad OFICIAL que IGDB da al juego. `name` es el fichero/carpeta real
    # (la ROM, p. ej. `After Burner.zip`); esto es cómo se llama el juego.
    igdb_name: str | None = None
    igdb_year: int | None = None


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


class TitleDetailOut(_ConPlataforma):
    slug: str
    name: str
    name_norm: str
    size_bytes: int
    file_count: int
    folder_count: int
    base_count: int
    update_count: int
    dlc_count: int
    formats: list[str]
    igdb_slug: str | None
    igdb_cover: str | None
    # Nombre canónico de IGDB y año del lanzamiento original (ver `TitleSummary`).
    igdb_name: str | None = None
    igdb_year: int | None = None
    ficha: dict | None = None  # ficha IGDB completa (ficha_v 2), si está enriquecido
    versions: list[VersionOut]
    remaining_files: list[FileOut]  # archivos directos del título (sin versión)


# ── novedades ────────────────────────────────────────────────
class NovedadOut(BaseModel):
    id: int
    tipo: str  # juego_nuevo | update_nuevo | dlc_nuevo | contenido_nuevo
    slug: str
    name: str
    letter: str
    version: str | None  # carpeta de versión del contenido nuevo (p. ej. "U-PD 1.3.0")
    archivos: int  # archivos nuevos de este evento
    bytes_nuevos: int
    detalle: list[str] = []  # rutas nuevas (relativas al título)
    igdb_cover: str | None
    detectada_en: datetime
    vigente: bool = True  # el título sigue en la biblioteca
    titulo: TitleSummary | None = None  # datos vivos del título (tarjeta)


class NovedadesOut(BaseModel):
    items: list[NovedadOut]
    total: int
    offset: int
    limit: int
    resumen: dict


# ── sync ─────────────────────────────────────────────────────
class SyncStatusOut(BaseModel):
    last_snapshot: SnapshotOut | None
    configured_dump: str
    dump_exists: bool
    # Frescura del volcado: si el refresco se para, la BD deja de actualizarse.
    dump_generated_at: str | None = None  # fecha de la cabecera del volcado
    dump_fuente: str | None = None  # share de la biblioteca (estable entre cuentas)
    dump_age_hours: float | None = None
    dump_max_edad_horas: int = 0
    dump_obsoleto: bool = False
    megacmd_available: bool
    megacmd_binary: str | None
    megacmd_error: str | None
    ultimo_escaneo: dict | None = None  # resumen del último diff aplicado


class CuentasEstadoOut(BaseModel):
    """Pre-vuelo de rotación MEGA: ¿la cuenta de la semana ve la biblioteca?

    Informe que escribe el host (`scripts/verificar_rotacion.py`, vía
    `make volcado`). `disponible=False` solo significa que no hay informe (pre-vuelo
    desactivado o aún sin ejecutar) y NO es un fallo: la UI debe alarmar cuando
    `ok` es False y no se forzó el vaciado.
    """

    disponible: bool = False
    ok: bool = True
    causa: str | None = None  # inshare_ausente | buckets_ausentes | sin_sesion | None
    veredicto: str | None = None  # frase legible del pre-vuelo
    forzado: bool = False  # se continuó a propósito (--permitir-otra-biblioteca)
    cuenta: str | None = None  # cuenta MEGA de la semana
    generado_en: str | None = None  # cuándo se comprobó (ISO 8601)
    edad_horas: float | None = None  # antigüedad de esa comprobación
    volcado: str | None = None  # volcado contra el que se verificó
    biblioteca: dict | None = None  # etiquetas, rutas, títulos, archivos, buckets
    faltan_rutas: list[str] = []
    faltan_buckets: dict[str, list[str]] = {}
    # Nube personal de la cuenta de turno (`mega-ls /`): rotan con las
    # credenciales y NO entran al catálogo (`entradas`, `nombres`).
    nube_propia: dict | None = None
    aviso: str | None = None  # explicación lista para la UI


class SyncRunOut(BaseModel):
    ok: bool
    snapshot: SnapshotOut | None = None
    resumen: dict | None = None
    error: str | None = None


# ── retro (sección aparte) ───────────────────────────────────
class RetroStatusOut(BaseModel):
    """Frescura de la colección retro (ROMs), que vive en SU PROPIA BD/volcado.

    Igual que el catálogo de Switch, la sección retro puede quedarse congelada en
    silencio si el refresco automático se rompe: la UI debe poder avisarlo.
    """

    disponible: bool = False  # hay snapshot retro en su BD
    snapshot: SnapshotOut | None = None
    juegos: int = 0
    sistemas: int = 0
    volcado: str
    volcado_existe: bool
    volcado_generated_at: str | None = None
    volcado_fuente: str | None = None  # in-share de las ROMs (estable entre cuentas)
    volcado_age_hours: float | None = None
    volcado_max_edad_horas: int = 0
    volcado_obsoleto: bool = False
    # Progreso del enriquecimiento IGDB de ESTA colección (lo lleva el worker
    # `backend-retro-enrich`, ver `app.enrich --coleccion retro`): la UI puede
    # enseñar cuánto falta sin mirar el catálogo de Switch.
    caratulas: int = 0  # títulos con portada IGDB
    enriquecidos: int = 0  # títulos con ficha IGDB COMPLETA (ficha_v 2)
    pendientes_enrich: int = 0  # sin match todavía o solo con ficha básica v1
    sin_match: int = 0  # probados y sin equivalencia en IGDB (miss)
    con_nombre_oficial: int = 0  # títulos con el nombre canónico de IGDB resuelto
    aviso: str | None = None
