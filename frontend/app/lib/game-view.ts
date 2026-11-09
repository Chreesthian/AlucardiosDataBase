import type { NovedadOut, TitleSummary } from "./api";
import {
  difiereOficial,
  extList,
  fechaLegible,
  formatBytes,
} from "./format";

/** Forma de presentar un catálogo: filas tipográficas o rejilla de carátulas. */
export type ViewMode = "lista" | "cuadricula";

export const VIEW_PARAM = "vista";

/** `lista` es SIEMPRE el valor por defecto (también sin parámetro). */
export function parseView(value: string | null | undefined): ViewMode {
  return value === "cuadricula" || value === "grid" ? "cuadricula" : "lista";
}

export const TYPE_LABEL: Record<string, string> = {
  juego_nuevo: "Juego nuevo",
  update_nuevo: "Actualización",
  dlc_nuevo: "DLC",
  contenido_nuevo: "Contenido",
};

/**
 * Modelo común de una fila/tarjeta. Las tres secciones (Biblioteca, Retro y
 * Novedades) lo consumen para que el mismo juego se vea igual en todas.
 */
export interface GameViewItem {
  key: string;
  name: string;
  subtitle: string | null;
  subtitleLabel: "IGDB" | "ROM" | null;
  href: string;
  titleAttr: string;
  year: number | null;
  platform: string | null;
  formats: string[];
  cover: string | null;
  sizeBytes: number;
  fileCount: number;
  facts: Array<[string, string]>;
  tags: string[];
  eyebrow: string;
  description: string | null;
  eventLabel: string | null;
  badge: string;
  gridMeta: string;
  index: number;
}

function statsSentence(game: TitleSummary): string {
  const parts = [`${game.file_count} archivos en MEGA`, formatBytes(game.size_bytes)];
  if (game.base_count) parts.push(`${game.base_count} base`);
  if (game.update_count) parts.push(`${game.update_count} update`);
  if (game.dlc_count) parts.push(`${game.dlc_count} DLC`);
  return `${parts.join(" · ")}.`;
}

/** Juego del catálogo de Switch o de la colección retro. */
export function titleItem(
  game: TitleSummary,
  opts: { href: string; preferCanonical?: boolean; index?: number },
): GameViewItem {
  const canonical = game.igdb_name?.trim() || "";
  const prefer = !!opts.preferCanonical && !!canonical;
  const name = prefer ? canonical : game.name;
  const subtitle = prefer
    ? game.name.toLowerCase() !== canonical.toLowerCase()
      ? game.name
      : null
    : difiereOficial(game.name, game.igdb_name)
      ? canonical
      : null;
  const formats = extList(game.ext_json);
  const platform = game.plataforma?.corto ?? game.letter;
  const year = game.igdb_year ?? null;

  const facts: Array<[string, string]> = [
    ["Tamaño", formatBytes(game.size_bytes)],
    ["Archivos", String(game.file_count)],
    ["Base", String(game.base_count)],
    ["Updates", String(game.update_count)],
  ];
  if (game.dlc_count) facts.push(["DLC", String(game.dlc_count)]);
  if (formats.length) facts.push(["Formatos", formats.join(" · ")]);

  return {
    key: game.slug,
    name,
    subtitle,
    subtitleLabel: prefer ? "ROM" : subtitle ? "IGDB" : null,
    href: opts.href,
    titleAttr: subtitle ? `${name} — ${subtitle}` : name,
    year,
    platform,
    formats,
    cover: game.igdb_cover,
    sizeBytes: game.size_bytes,
    fileCount: game.file_count,
    facts,
    tags: [...formats, platform].filter(Boolean) as string[],
    eyebrow: [game.plataforma?.nombre ?? `Bucket ${game.letter}`, year ?? "año s/d"]
      .filter(Boolean)
      .join(" · "),
    description: statsSentence(game),
    eventLabel: null,
    badge: platform,
    gridMeta: [year, platform, formatBytes(game.size_bytes)]
      .filter(Boolean)
      .join(" · "),
    index: opts.index ?? 0,
  };
}

/** Evento de "Novedades" (juego nuevo, update, DLC o contenido). */
export function eventItem(
  event: NovedadOut,
  opts: { href: string; index?: number },
): GameViewItem {
  const title = event.titulo;
  const official = title?.igdb_name?.trim() || "";
  const name = event.name;
  const subtitle = official && official.toLowerCase() !== name.toLowerCase() ? official : null;
  const platform = title?.plataforma?.corto ?? event.letter;
  const formats = extList(title?.ext_json ?? null);
  const typeLabel = TYPE_LABEL[event.tipo] ?? event.tipo;
  const date = fechaLegible(event.detectada_en);
  const size = formatBytes(event.bytes_nuevos);

  const facts: Array<[string, string]> = [
    ["Archivos", String(event.archivos)],
    ["Nuevos", size],
    ["Versión", event.version ?? "—"],
    ["Detectado", date],
  ];

  return {
    key: `ev-${event.id}`,
    name,
    subtitle,
    subtitleLabel: subtitle ? "IGDB" : null,
    href: opts.href,
    titleAttr: title ? `${name} — ${title.name}` : name,
    year: title?.igdb_year ?? null,
    platform,
    formats,
    cover: event.igdb_cover ?? title?.igdb_cover ?? null,
    sizeBytes: title?.size_bytes ?? event.bytes_nuevos,
    fileCount: title?.file_count ?? event.archivos,
    facts,
    tags: [typeLabel, event.version].filter(Boolean) as string[],
    eyebrow: `${typeLabel} · ${date}`,
    description: `Han entrado ${event.archivos} archivos nuevos (${size}).`,
    eventLabel: `${typeLabel} · ${date}`,
    badge: typeLabel,
    gridMeta: `${date} · ${event.archivos} archivos · ${size}`,
    index: opts.index ?? 0,
  };
}
