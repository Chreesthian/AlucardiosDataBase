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

export interface BucketOut {
  letter: string;
  titles: number;
  size_bytes: number;
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
  size_bytes: number;
  file_count: number;
  base_count: number;
  update_count: number;
  dlc_count: number;
  ext_json: string | null;
  igdb_cover: string | null;
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
  size_bytes: number;
  file_count: number;
  folder_count: number;
  base_count: number;
  update_count: number;
  dlc_count: number;
  formats: string[];
  igdb_slug: string | null;
  igdb_cover: string | null;
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

export const api = {
  meta: () => getJSON<MetaOut>("/api/meta"),
  syncStatus: () => getJSON<SyncStatusOut>("/api/sync/status"),
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
};
