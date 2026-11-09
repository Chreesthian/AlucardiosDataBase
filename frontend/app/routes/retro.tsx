import type { LoaderFunctionArgs, MetaFunction } from "react-router";
import { Link, useLoaderData } from "react-router";

import { GameGrid } from "~/components/GameGrid";
import { GameRows } from "~/components/GameRows";
import { SearchBox } from "~/components/SearchBox";
import { SiteFooter } from "~/components/SiteFooter";
import { ViewToggle } from "~/components/ViewToggle";
import { api } from "~/lib/api";
import { parseView, titleItem, VIEW_PARAM } from "~/lib/game-view";
import { edadLegible, formatBytes, formatNumber } from "~/lib/format";

const LIMIT = 60;

export const meta: MetaFunction = () => [
  { title: "Retro — AlucardiosDataBase" },
  {
    name: "description",
    content:
      "Colección de ROMs retro (arcade, consolas y microordenadores) en MEGA, con su propio volcado y fichas IGDB.",
  },
];

function mkQuery(
  current: { q: string; sistema: string; sort: string; vista?: string },
  over: Record<string, string | number | null | undefined>,
): string {
  const sp = new URLSearchParams();
  const merged: Record<string, string | number | null | undefined> = {
    q: current.q || undefined,
    sistema: current.sistema || undefined,
    sort: current.sort || undefined,
    vista: current.vista && current.vista !== "lista" ? current.vista : undefined,
    ...over,
  };
  for (const [key, value] of Object.entries(merged)) {
    if (value === undefined || value === null || value === "" || value === 0) continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function loader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  const q = url.searchParams.get("q") ?? "";
  const sistema = url.searchParams.get("sistema") ?? "";
  const sort = (url.searchParams.get("sort") ?? "canonico") as
    | "canonico"
    | "name"
    | "year"
    | "size"
    | "files";
  const offset = Math.max(0, Number.parseInt(url.searchParams.get("offset") ?? "0", 10) || 0);
  const view = parseView(url.searchParams.get(VIEW_PARAM));

  try {
    const [meta, sistemas, list, estado] = await Promise.all([
      api.retroMeta(),
      api.retroSistemas(),
      api.retroTitles({
        q: q || undefined,
        sistema: sistema || undefined,
        sort,
        offset,
        limit: LIMIT,
      }),
      api.retroStatus().catch(() => null),
    ]);
    return { q, sistema, sort, offset, view, meta, sistemas, list, estado, error: null };
  } catch (error) {
    return {
      q,
      sistema,
      sort,
      offset,
      view,
      meta: null,
      sistemas: [],
      list: null,
      estado: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export default function Retro() {
  const { q, sistema, sort, offset, view, meta, sistemas, list, estado, error } =
    useLoaderData<typeof loader>();

  const current = { q, sistema, sort, vista: view };
  const items = list?.items ?? [];
  const total = list?.total ?? 0;
  const hasNext = offset + items.length < total;
  const viewItems = items.map((game, index) =>
    titleItem(game, {
      href: `/retro/game/${game.slug}/`,
      preferCanonical: true,
      index,
    }),
  );
  const listHref = `/retro${mkQuery(current, { vista: null, offset: offset || undefined })}`;
  const gridHref = `/retro${mkQuery(current, { vista: "cuadricula", offset: offset || undefined })}`;

  return (
    <>
      <section className="page-head page-shell">
        <p className="page-head__eyebrow">
          <Link to="/" className="back-link" style={{ minHeight: "auto" }}>
            ← Biblioteca
          </Link>
          <span>Colección aparte · otro in-share</span>
        </p>
        <h1 className="page-head__title">Retro.</h1>
        <p className="page-head__note">
          Arcade, consolas y microordenadores de siempre, reunidos en un solo
          sitio. Elige un sistema, abre la ficha y descarga la ROM desde MEGA.
        </p>
        <div className="page-head__stats">
          <span>
            <b>{meta ? formatNumber(meta.titles) : "—"}</b> juegos
          </span>
          <span>
            <b>{sistemas.length || "—"}</b> sistemas
          </span>
          <span>
            <b>{meta ? formatNumber(meta.files) : "—"}</b> archivos
          </span>
          <span>
            <b>{meta ? formatBytes(meta.bytes) : "—"}</b> en MEGA
          </span>
          <span>
            Actualizado <b>{estado ? `hace ${edadLegible(estado.volcado_age_hours)}` : "—"}</b>
          </span>
        </div>
      </section>

      {error ? (
        <div className="page-shell">
          <div className="empty-state">{error}</div>
        </div>
      ) : null}

      <div className="page-shell" style={{ paddingBottom: "var(--space-section)" }}>
        <div className="library-tools">
          <SearchBox
            mode="retro"
            initialQuery={q}
            hiddenParams={{
              sistema,
              sort,
              ...(view === "cuadricula" ? { vista: view } : {}),
            }}
          />
          <nav className="chip-row" aria-label="Sistemas">
            <Link
              to={`/retro${mkQuery(current, { sistema: "", offset: 0 })}`}
              className="chip"
              data-active={sistema === ""}
            >
              Todos
            </Link>
            {sistemas.map((bucket) => (
              <Link
                key={bucket.letter}
                to={`/retro${mkQuery(current, { sistema: bucket.letter, offset: 0 })}`}
                className="chip"
                data-active={sistema === bucket.letter}
                title={`${bucket.titles} juegos · ${bucket.plataforma?.nombre ?? bucket.letter}`}
              >
                {bucket.plataforma?.corto ?? bucket.letter}
                <small>{bucket.titles}</small>
              </Link>
            ))}
          </nav>

          <div className="toolbar-meta">
            <span>Ordenar:</span>
            {(
              [
                ["canonico", "Canónico"],
                ["name", "Nombre"],
                ["year", "Año"],
                ["size", "Tamaño"],
                ["files", "Archivos"],
              ] as const
            ).map(([value, label]) => (
              <Link
                key={value}
                to={`/retro${mkQuery(current, { sort: value, offset: 0 })}`}
                data-active={sort === value}
              >
                {label}
              </Link>
            ))}
          </div>
          <div className="view-bar">
            <span className="view-bar__count">
              {total} resultados{sistema ? ` · ${sistema}` : ""}
            </span>
            <ViewToggle view={view} listHref={listHref} gridHref={gridHref} />
          </div>
        </div>

        {view === "cuadricula" ? (
          <GameGrid items={viewItems} />
        ) : (
          <GameRows items={viewItems} offset={offset} />
        )}

        <nav className="pager" aria-label="Paginación">
          {offset > 0 ? (
            <Link to={`/retro${mkQuery(current, { offset: Math.max(0, offset - LIMIT) })}`}>
              ← Anterior
            </Link>
          ) : (
            <span aria-hidden="true">← Anterior</span>
          )}
          <span className="text-subtle">
            {offset + 1}–{offset + items.length} de {total}
          </span>
          {hasNext ? (
            <Link to={`/retro${mkQuery(current, { offset: offset + LIMIT })}`}>
              Siguiente →
            </Link>
          ) : (
            <span aria-hidden="true">Siguiente →</span>
          )}
        </nav>
      </div>

      <SiteFooter meta={meta} sync={null} />
    </>
  );
}
