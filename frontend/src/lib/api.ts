// Cliente tipado de la API (análogo a scrob frontend/src/lib/api.ts).
// El backend por defecto escucha en http://localhost:7331 (igual que scrob).

const BACKEND_HOST = import.meta.env.PUBLIC_BACKEND_HOST ?? "http://localhost";
const BACKEND_PORT = import.meta.env.PUBLIC_BACKEND_PORT ?? "7331";
export const API_BASE = `${BACKEND_HOST}:${BACKEND_PORT}`;

export interface SnapshotOut {
  id: number;
  account: string | null;
  tool: string | null;
  generated_at: string | null;
  source_kind: string;
  source_path: string | null;
  content_sha256: string | null;
  ingested_at: string;
  file_count: number;
  folder_count: number;
  total_size: number;
}

/**
 * Sistema/plataforma OFICIAL de un bucket del catálogo (ver `app.plataformas`).
 *
 * `letter` sigue siendo la identidad del bucket en el volcado (la letra A-Z en
 * Switch, el sistema `ARC N-64` en retro): esto es cómo se llama de verdad esa
 * plataforma. `conocido=false` avisa de un código del volcado que todavía no
 * está en el catálogo oficial (se publica tal cual, sin inventar nombres).
 */
export interface PlataformaOut {
  clave: string;
  nombre: string;
  corto: string;
  igdb_id: number | null;
  igdb_slug: string | null;
  generacion: number | null;
  familia: string | null;
  conocido: boolean;
}

export interface BucketOut {
  letter: string;
  titles: number;
  size_bytes: number;
  plataforma?: PlataformaOut | null;
}

export interface MetaOut {
  snapshot: SnapshotOut | null;
  titles: number;
  files: number;
  folders: number;
  bytes: number;
  covers?: number;
  buckets: BucketOut[];
}

export interface CardGame {
  slug: string;
  name: string;
  letter: string;
  /** Sistema/plataforma OFICIAL del bucket (Switch también lo publica). */
  plataforma?: PlataformaOut | null;
  size_bytes: number;
  file_count: number;
  base_count: number;
  update_count: number;
  dlc_count: number;
  ext_json: string | null;
  igdb_cover: string | null;
  /** Nombre OFICIAL que IGDB da al juego (`name` es el fichero/carpeta real). */
  igdb_name?: string | null;
  /** Año del lanzamiento original según IGDB (si la ficha lo trae). */
  igdb_year?: number | null;
}

export interface TitleSummary extends CardGame {
  folder_count: number;
  other_count: number;
  igdb_slug: string | null;
}

export interface TitleListOut {
  items: TitleSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface FileOut {
  name: string;
  size: number;
  ext: string | null;
  path: string;
  full_path?: string | null;
}

export interface VersionOut {
  id: number;
  name: string;
  label: string;
  size_bytes: number;
  file_count: number;
  folder_count: number;
  full_path?: string | null;
  files: FileOut[];
}

export interface TitleDetailOut {
  slug: string;
  name: string;
  name_norm: string;
  letter: string;
  /** Sistema/plataforma OFICIAL del bucket (`letter` es el código del volcado). */
  plataforma?: PlataformaOut | null;
  size_bytes: number;
  file_count: number;
  folder_count: number;
  base_count: number;
  update_count: number;
  dlc_count: number;
  formats: string[];
  igdb_slug: string | null;
  igdb_cover: string | null;
  igdb_name?: string | null;
  igdb_year?: number | null;
  ficha?: Record<string, any> | null;
  versions: VersionOut[];
  remaining_files: FileOut[];
}

export interface SyncStatusOut {
  last_snapshot: SnapshotOut | null;
  configured_dump: string;
  dump_exists: boolean;
  /** Fecha de la cabecera del volcado (cuándo se refrescó de verdad). */
  dump_generated_at: string | null;
  /** Share que aporta la biblioteca (estable aunque la cuenta rote). */
  dump_fuente: string | null;
  /** Horas transcurridas desde el último refresco del volcado. */
  dump_age_hours: number | null;
  dump_max_edad_horas: number;
  /** `true` cuando el pipeline de actualización está parado. */
  dump_obsoleto: boolean;
  megacmd_available: boolean;
  megacmd_binary: string | null;
  megacmd_error: string | null;
  ultimo_escaneo: Record<string, unknown> | null;
}

/**
 * Pre-vuelo de rotación MEGA (`GET /api/sync/cuentas`): lo escribe el host al
 * refrescar el volcado y dice si las credenciales de la semana ven LA MISMA
 * biblioteca. `disponible === false` solo significa que no hay informe (no es un
 * fallo); la alarma es `ok === false` sin `forzado`.
 */
export interface CuentasEstadoOut {
  disponible: boolean;
  ok: boolean;
  /** `inshare_ausente` | `buckets_ausentes` | `sin_sesion` | `null`. */
  causa: string | null;
  /** Frase legible del pre-vuelo (la usa el aviso en pantalla). */
  veredicto: string | null;
  /** El vaciado se permitió a propósito (`--permitir-otra-biblioteca`). */
  forzado: boolean;
  /** Cuenta MEGA con la que se verificó (rota cada semana). */
  cuenta: string | null;
  generado_en: string | null;
  /** Antigüedad de esa comprobación, en horas. */
  edad_horas: number | null;
  volcado: string | null;
  /** `etiquetas`, `rutas`, `titulos`, `files`, `buckets_esperados`. */
  biblioteca: Record<string, unknown> | null;
  faltan_rutas: string[];
  faltan_buckets: Record<string, string[]>;
  /**
   * Nube personal de la cuenta de turno (`mega-ls /`): rota con las credenciales
   * y NO entra al catálogo (solo se indexa la biblioteca).
   */
  nube_propia: { entradas?: number; nombres?: string[] } | null;
  aviso: string | null;
}

export type TipoNovedad = "juego_nuevo" | "update_nuevo" | "dlc_nuevo" | "contenido_nuevo";

export interface NovedadOut {
  id: number;
  tipo: TipoNovedad;
  slug: string;
  name: string;
  letter: string;
  version: string | null;
  archivos: number;
  bytes_nuevos: number;
  detalle: string[];
  igdb_cover: string | null;
  detectada_en: string;
  vigente: boolean;
  titulo?: TitleSummary | null;
}

export interface NovedadesOut {
  items: NovedadOut[];
  total: number;
  offset: number;
  limit: number;
  resumen: {
    total: number;
    por_tipo: Record<TipoNovedad, number>;
    juegos_nuevos: number;
    actualizaciones: number;
  };
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* no body */
    }
    throw new Error(`API ${res.status}: ${path} ${detail}`.trim());
  }
  return res.json() as Promise<T>;
}

export interface TitlesParams {
  q?: string;
  letter?: string;
  sort?: "name" | "size" | "files";
  offset?: number;
  limit?: number;
}

export interface NovedadesParams {
  tipo?: string;
  offset?: number;
  limit?: number;
}

/**
 * Colección RETRO (ROMs): catálogo APARTE del de Switch, con su propia BD y su
 * propio volcado. `sistema` es la PLATAFORMA del juego y acepta su clave
 * canónica (`mega-drive`), su nombre oficial (`Sega Mega Drive/Genesis`) o el
 * código del volcado (`ARC S3G4-Mega Drive-G3N3S1S`, que es lo que acaba en el
 * `letter` del backend): el backend los traduce todos con `app.plataformas`.
 */
export interface RetroStatusOut {
  disponible: boolean;
  snapshot: SnapshotOut | null;
  juegos: number;
  sistemas: number;
  volcado: string;
  volcado_existe: boolean;
  volcado_generated_at: string | null;
  volcado_fuente: string | null;
  volcado_age_hours: number | null;
  volcado_max_edad_horas: number;
  volcado_obsoleto: boolean;
  /** Progreso del enriquecimiento IGDB de esta colección (worker `backend-retro-enrich`). */
  caratulas: number;
  enriquecidos: number;
  pendientes_enrich: number;
  sin_match: number;
  /** Títulos con el nombre canónico de IGDB resuelto. */
  con_nombre_oficial: number;
  aviso: string | null;
}

export interface RetroParams {
  q?: string;
  sistema?: string;
  sort?: "canonico" | "name" | "year" | "size" | "files";
  offset?: number;
  limit?: number;
}

export const api = {
  meta: () => getJSON<MetaOut>("/api/meta"),
  syncStatus: () => getJSON<SyncStatusOut>("/api/sync/status"),
  cuentasEstado: () => getJSON<CuentasEstadoOut>("/api/sync/cuentas"),
  titles: (params: TitlesParams = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set("q", params.q);
    if (params.letter) sp.set("letter", params.letter);
    if (params.sort) sp.set("sort", params.sort);
    if (params.offset !== undefined) sp.set("offset", String(params.offset));
    if (params.limit !== undefined) sp.set("limit", String(params.limit));
    return getJSON<TitleListOut>(`/api/titles?${sp.toString()}`);
  },
  title: (slug: string) =>
    getJSON<TitleDetailOut>(`/api/titles/${encodeURIComponent(slug)}`),
  novedades: (params: NovedadesParams = {}) => {
    const sp = new URLSearchParams();
    if (params.tipo) sp.set("tipo", params.tipo);
    if (params.offset !== undefined) sp.set("offset", String(params.offset));
    if (params.limit !== undefined) sp.set("limit", String(params.limit));
    return getJSON<NovedadesOut>(`/api/novedades?${sp.toString()}`);
  },
  // ── Sección RETRO (ROMs), aparte de la biblioteca de Switch ──
  retroMeta: () => getJSON<MetaOut>("/api/retro/meta"),
  retroSistemas: () => getJSON<BucketOut[]>("/api/retro/sistemas"),
  retroStatus: () => getJSON<RetroStatusOut>("/api/retro/status"),
  retroTitles: (params: RetroParams = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set("q", params.q);
    if (params.sistema) sp.set("sistema", params.sistema);
    if (params.sort) sp.set("sort", params.sort);
    if (params.offset !== undefined) sp.set("offset", String(params.offset));
    if (params.limit !== undefined) sp.set("limit", String(params.limit));
    return getJSON<TitleListOut>(`/api/retro/titles?${sp.toString()}`);
  },
  retroTitle: (slug: string) =>
    getJSON<TitleDetailOut>(`/api/retro/titles/${encodeURIComponent(slug)}`),
};
