/**
 * Cliente tipado de la API del catálogo (FastAPI).
 *
 * En SSR se usa la URL INTERNA horneada en el build
 * (`PUBLIC_BACKEND_HOST=http://backend` dentro de Docker); en el navegador se
 * usa `window.__ALUCARD_API`, que `root.tsx` inyecta con el puerto público del
 * compose (`ALUCARD_PUBLIC_BACKEND_PORT`). El bundle nunca apunta a
 * `http://backend` desde el cliente.
 */

const ENV_HOST = import.meta.env.PUBLIC_BACKEND_HOST ?? "http://localhost";
const ENV_PORT = import.meta.env.PUBLIC_BACKEND_PORT ?? "7331";

export function apiBase(): string {
  if (typeof window === "undefined") return `${ENV_HOST}:${ENV_PORT}`;
  const injected = (window as { __ALUCARD_API?: string }).__ALUCARD_API;
  return injected || `${window.location.protocol}//${window.location.hostname}:${ENV_PORT}`;
}

// ── payloads ────────────────────────────────────────────────────────────────
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
  plataforma?: PlataformaOut | null;
  size_bytes: number;
  file_count: number;
  base_count: number;
  update_count: number;
  dlc_count: number;
  ext_json: string | null;
  igdb_cover: string | null;
  igdb_name?: string | null;
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

export interface FichaIGDB {
  ficha_v?: number;
  nombre_oficial?: string | null;
  slug?: string | null;
  /** Sinopsis principal servida por IGDB. */
  descripcion?: string | null;
  /** Historia/argumento adicional cuando IGDB lo publica. */
  argumento?: string | null;
  caratula?: string | null;
  rating?: number | null;
  rating_agregado?: number | null;
  rating_total?: number | null;
  votos?: number | null;
  votos_total?: number | null;
  pegi?: string | null;
  plataformas?: string[] | string | null;
  generos?: string[] | string | null;
  temas?: string[] | string | null;
  modos?: string[] | string | null;
  perspectivas?: string[] | string | null;
  palabras_clave?: string[] | string | null;
  desarrollador?: string | null;
  publicador?: string | null;
  fecha_lanzamiento?: string | null;
  estado?: string | null;
  capturas?: string[] | null;
  videos?: Array<{ nombre?: string; video_id?: string }> | null;
  webs?: Array<{ categoria?: string; url?: string }> | null;
  similares?: Array<{
    nombre?: string;
    slug?: string;
    caratula?: string | null;
    rating?: number | null;
  }> | null;
  coleccion?: string | null;
  franquicia?: string | null;
  url_igdb?: string | null;
  artworks?: string[] | null;
  hero_imagen?: string | null;
  lanzamientos?: Array<{
    plataforma?: string;
    fecha?: string;
    humano?: string;
    region?: string | null;
  }> | null;
  enlaces?: Array<{ etiqueta?: string; url?: string }> | null;
  clasificaciones?: Array<{ sistema?: string; texto?: string }> | null;
  idiomas_soporte?: string[] | null;
  [key: string]: unknown;
}

export interface TitleDetailOut {
  slug: string;
  name: string;
  name_norm: string;
  letter: string;
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
  ficha?: FichaIGDB | null;
  versions: VersionOut[];
  remaining_files: FileOut[];
}

export interface SyncStatusOut {
  last_snapshot: SnapshotOut | null;
  configured_dump: string;
  dump_exists: boolean;
  dump_generated_at: string | null;
  dump_fuente: string | null;
  dump_age_hours: number | null;
  dump_max_edad_horas: number;
  dump_obsoleto: boolean;
  megacmd_available: boolean;
  megacmd_binary: string | null;
  megacmd_error: string | null;
  ultimo_escaneo: Record<string, unknown> | null;
}

export interface CuentasEstadoOut {
  disponible: boolean;
  ok: boolean;
  causa: string | null;
  veredicto: string | null;
  forzado: boolean;
  cuenta: string | null;
  generado_en: string | null;
  edad_horas: number | null;
  volcado: string | null;
  biblioteca: Record<string, unknown> | null;
  faltan_rutas: string[];
  faltan_buckets: Record<string, string[]>;
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
  caratulas: number;
  enriquecidos: number;
  pendientes_enrich: number;
  sin_match: number;
  con_nombre_oficial: number;
  aviso: string | null;
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

export interface RetroParams {
  q?: string;
  sistema?: string;
  sort?: "canonico" | "name" | "year" | "size" | "files";
  offset?: number;
  limit?: number;
}

// ── transporte ──────────────────────────────────────────────────────────────
async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      /* sin cuerpo */
    }
    throw new Error(`API ${res.status}: ${path}${detail ? ` ${detail}` : ""}`);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  meta: () => getJSON<MetaOut>("/api/meta"),
  buckets: () => getJSON<BucketOut[]>("/api/buckets"),
  syncStatus: () => getJSON<SyncStatusOut>("/api/sync/status"),
  cuentasEstado: () => getJSON<CuentasEstadoOut>("/api/sync/cuentas"),
  titles: (params: TitlesParams = {}) =>
    getJSON<TitleListOut>(`/api/titles${qs({ ...params })}`),
  title: (slug: string) =>
    getJSON<TitleDetailOut>(`/api/titles/${encodeURIComponent(slug)}`),
  novedades: (params: NovedadesParams = {}) =>
    getJSON<NovedadesOut>(`/api/novedades${qs({ ...params })}`),
  retroMeta: () => getJSON<MetaOut>("/api/retro/meta"),
  retroSistemas: () => getJSON<BucketOut[]>("/api/retro/sistemas"),
  retroStatus: () => getJSON<RetroStatusOut>("/api/retro/status"),
  retroTitles: (params: RetroParams = {}) =>
    getJSON<TitleListOut>(`/api/retro/titles${qs({ ...params })}`),
  retroTitle: (slug: string) =>
    getJSON<TitleDetailOut>(`/api/retro/titles/${encodeURIComponent(slug)}`),
  search: (q: string, limit = 8, signal?: AbortSignal) =>
    getJSON<TitleListOut>(`/api/titles${qs({ q, limit })}`, signal),
  retroSearch: (q: string, limit = 8, signal?: AbortSignal) =>
    getJSON<TitleListOut>(`/api/retro/titles${qs({ q, limit })}`, signal),
};
