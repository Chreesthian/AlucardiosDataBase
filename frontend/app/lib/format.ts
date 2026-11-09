/** Utilidades de formato compartidas por todas las vistas. */

export function formatBytes(value: number): string {
  if (!value || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let v = value;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return u === 0 ? `${v} B` : `${v.toFixed(1)} ${units[u]}`;
}

export function formatNumber(value: number): string {
  try {
    return new Intl.NumberFormat("es-ES").format(value);
  } catch {
    return String(value);
  }
}

export function extList(extJson?: string | null): string[] {
  if (!extJson) return [];
  try {
    const data = JSON.parse(extJson) as Record<string, number>;
    return Object.entries(data)
      .filter(([, n]) => n > 0)
      .map(([k]) => k.toUpperCase())
      .sort();
  } catch {
    return [];
  }
}

export function initials(name: string): string {
  const parts = name.split(/[\s\-_:]+/).filter(Boolean);
  const two = parts
    .slice(0, 2)
    .map((p) => p[0] ?? "")
    .join("");
  return (two || name.slice(0, 2)).toUpperCase();
}

/**
 * URL de carátula de IGDB. `big` pide la variante 2x para el panel y la ficha
 * (se ven a ~320-400 px); la rejilla usa la 1x para no disparar el peso.
 */
export function coverUrl(
  url?: string | null,
  size: "grid" | "big" = "grid",
): string | null {
  if (!url) return null;
  if (size === "big") {
    return url.replace("/t_cover_big/", "/t_cover_big_2x/");
  }
  return url;
}

/** Miniatura o versión completa de una captura de IGDB. */
export function screenshotUrl(
  url?: string | null,
  size: "thumb" | "full" = "thumb",
): string | null {
  if (!url) return null;
  const target = size === "thumb" ? "t_screenshot_med" : "t_screenshot_huge";
  return url.replace(/\/t_screenshot_[a-z0-9_]+\//, `/${target}/`);
}

/** Los artworks de IGDB ya vienen en t_1080p; se dejan tal cual. */
export function bannerUrl(url?: string | null): string | null {
  if (!url) return null;
  return url.replace("/t_cover_big/", "/t_cover_big_2x/");
}

/** Número de fila con dos dígitos (01, 02… como en el original). */
export function rowIndex(n: number): string {
  return String(n).padStart(2, "0");
}

/** Fechas de SQLite sin zona: se interpretan como UTC para no bailar por TZ. */
export function fechaLegible(iso?: string | null): string {
  if (!iso) return "";
  const conZona = /(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(conZona.length === 10 ? `${iso}T00:00:00Z` : conZona);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return d.toLocaleDateString("es-ES", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export function edadLegible(horas: number | null | undefined): string {
  if (horas === null || horas === undefined) return "sin datos";
  if (horas < 1) return `${Math.max(1, Math.round(horas * 60))} min`;
  if (horas < 48) return `${Math.round(horas)} h`;
  return `${Math.round(horas / 24)} días`;
}

/** Nombre canónico de IGDB (si existe). */
export function nombreOficial(name?: string | null, igdbName?: string | null): string | null {
  const oficial = (igdbName ?? "").trim();
  if (!oficial) return null;
  return oficial;
}

/** ¿El nombre oficial aporta algo distinto del nombre real? */
export function difiereOficial(name: string, igdbName?: string | null): boolean {
  const oficial = (igdbName ?? "").trim();
  if (!oficial) return false;
  return normalizar(oficial) !== normalizar(name);
}

export function normalizar(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Lista legible de un campo de ficha (string | string[] | null). */
export function joinField(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value)) {
    const items = value.map((v) => String(v)).filter(Boolean);
    return items.length ? items.join(" · ") : null;
  }
  const s = String(value).trim();
  return s || null;
}

export function first(value: unknown): string | null {
  if (Array.isArray(value)) return value.length ? String(value[0]) : null;
  if (value === null || value === undefined) return null;
  const s = String(value).trim();
  return s || null;
}
