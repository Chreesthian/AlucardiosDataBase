import type { LoaderFunctionArgs, MetaFunction } from "react-router";
import { Link, useLoaderData } from "react-router";

import { BandEdge } from "~/components/BandEdge";
import { GameGrid } from "~/components/GameGrid";
import { GameRows } from "~/components/GameRows";
import { Hero } from "~/components/Hero";
import { Reveal } from "~/components/Reveal";
import { SearchBox } from "~/components/SearchBox";
import { SiteFooter } from "~/components/SiteFooter";
import { ViewToggle } from "~/components/ViewToggle";
import { Wordmark } from "~/components/Wordmark";
import { api } from "~/lib/api";
import { parseView, titleItem, VIEW_PARAM } from "~/lib/game-view";
import { fechaLegible, formatBytes, formatNumber } from "~/lib/format";

const LIMIT = 60;

export const meta: MetaFunction = () => [
  { title: "AlucardiosDataBase — Biblioteca" },
  {
    name: "description",
    content:
      "Explora la biblioteca de juegos de Switch de tu cuenta MEGA: portadas, fichas IGDB, versiones, updates y DLC.",
  },
];

function mkQuery(
  current: { q: string; letter: string; sort: string; vista?: string },
  over: Record<string, string | number | null | undefined>,
): string {
  const sp = new URLSearchParams();
  const merged: Record<string, string | number | null | undefined> = {
    q: current.q || undefined,
    letter: current.letter || undefined,
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
  const letter = url.searchParams.get("letter") ?? "";
  const sort = (url.searchParams.get("sort") ?? "name") as "name" | "size" | "files";
  const offset = Math.max(0, Number.parseInt(url.searchParams.get("offset") ?? "0", 10) || 0);
  const view = parseView(url.searchParams.get(VIEW_PARAM));

  try {
    const [meta, list, novedades, retroMeta, sync] = await Promise.all([
      api.meta(),
      api.titles({ q: q || undefined, letter: letter || undefined, sort, offset, limit: LIMIT }),
      api.novedades({ limit: 12 }).catch(() => null),
      api.retroMeta().catch(() => null),
      api.syncStatus().catch(() => null),
    ]);
    return { q, letter, sort, offset, view, meta, list, novedades, retroMeta, sync, error: null };
  } catch (error) {
    return {
      q,
      letter,
      sort,
      offset,
      view,
      meta: null,
      list: null,
      novedades: null,
      retroMeta: null,
      sync: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export default function Home() {
  const { q, letter, sort, offset, view, meta, list, novedades, retroMeta, sync, error } =
    useLoaderData<typeof loader>();

  const current = { q, letter, sort, vista: view };
  const items = list?.items ?? [];
  const total = list?.total ?? 0;
  const buckets = meta?.buckets ?? [];
  const hasNext = offset + items.length < total;
  const novedadesItems = novedades?.items?.slice(0, 12) ?? [];
  const resumen = novedades?.resumen;
  const viewItems = items.map((game, index) =>
    titleItem(game, { href: `/game/${game.slug}/`, index }),
  );
  const listHref = `/${mkQuery(current, { vista: null, offset: offset || undefined })}`;
  const gridHref = `/${mkQuery(current, { vista: "cuadricula", offset: offset || undefined })}`;

  const typeLabel: Record<string, string> = {
    juego_nuevo: "Juego nuevo",
    update_nuevo: "Update",
    dlc_nuevo: "DLC",
    contenido_nuevo: "Contenido",
  };

  return (
    <>
      <h1 className="sr-only" id="page-title">
        Biblioteca
      </h1>

      <Hero
        wordmark={<Wordmark />}
        meta={
          <>
            <b>{meta ? formatNumber(meta.titles) : "—"}</b> juegos ·{" "}
            <b>{meta ? formatNumber(meta.files) : "—"}</b> archivos
          </>
        }
      />

      <section id="biblioteca" className="work-section section" aria-label="Biblioteca">

        {error ? (
          <div className="notice notice--warn" role="alert">
            <b>No se pudo conectar con la API.</b>
            <span>{error}</span>
            <span>
              Arranca el backend en :7331 (<code>uv run uvicorn app.main:app --port 7331</code>).
            </span>
          </div>
        ) : null}

        <Reveal className="library-tools" delay={80}>
          <SearchBox
            initialQuery={q}
            hiddenParams={view === "cuadricula" ? { vista: view } : {}}
          />

          <nav className="chip-row" aria-label="Letras">
            <Link
              to={`/${mkQuery(current, { letter: "", offset: 0 })}`}
              className="chip"
              data-active={letter === ""}
            >
              Todas
            </Link>
            {buckets.map((bucket) => (
              <Link
                key={bucket.letter}
                to={`/${mkQuery(current, { letter: bucket.letter, offset: 0 })}`}
                className="chip"
                data-active={letter === bucket.letter}
                title={`${bucket.titles} juegos`}
              >
                {bucket.letter}
                <small>{bucket.titles}</small>
              </Link>
            ))}
          </nav>

          <div className="toolbar-meta">
            <span>Ordenar:</span>
            {(
              [
                ["name", "Nombre"],
                ["size", "Tamaño"],
                ["files", "Archivos"],
              ] as const
            ).map(([value, label]) => (
              <Link
                key={value}
                to={`/${mkQuery(current, { sort: value, offset: 0 })}`}
                data-active={sort === value}
              >
                {label}
              </Link>
            ))}
          </div>
          <div className="view-bar">
            <span className="view-bar__count">
              {total} resultados{letter ? ` · letra ${letter}` : ""}
            </span>
            <ViewToggle view={view} listHref={listHref} gridHref={gridHref} />
          </div>
        </Reveal>

        {view === "cuadricula" ? (
          <GameGrid items={viewItems} />
        ) : (
          <GameRows items={viewItems} offset={offset} />
        )}

        <nav className="pager" aria-label="Paginación">
          {offset > 0 ? (
            <Link to={`/${mkQuery(current, { offset: Math.max(0, offset - LIMIT) })}`}>
              ← Anterior
            </Link>
          ) : (
            <span aria-hidden="true">← Anterior</span>
          )}
          <span className="text-subtle">
            {offset + 1}–{offset + items.length} de {total}
          </span>
          {hasNext ? (
            <Link to={`/${mkQuery(current, { offset: offset + LIMIT })}`}>Siguiente →</Link>
          ) : (
            <span aria-hidden="true">Siguiente →</span>
          )}
        </nav>
      </section>



      {novedadesItems.length ? (
        <section className="band" aria-labelledby="novedades-title">
          <BandEdge position="top" />
          <div className="band__inner">
            <p className="mono-label">Lo último que ha entrado</p>
            <h2 id="novedades-title" className="giant-type" style={{ marginTop: "0.6rem" }}>
              Novedades
            </h2>
            <p
              className="mono-label"
              style={{ marginTop: "0.9rem", maxWidth: "48ch", lineHeight: 1.5 }}
            >
              Juegos completos nuevos y títulos que han recibido archivos de
              actualización o DLC en el último volcado.
            </p>

            <div className="wall">
              {novedadesItems.map((evento) => {
                const titulo = evento.titulo?.igdb_name?.trim() || evento.name;
                return (
                  <Link
                    key={evento.id}
                    to={`/game/${evento.slug}/`}
                    className="wall__item"
                    data-cursor
                    data-cursor-label="Abrir"
                  >
                    <span className="wall__kicker">
                      {typeLabel[evento.tipo] ?? evento.tipo} ·{" "}
                      {fechaLegible(evento.detectada_en)}
                    </span>
                    <span className="wall__name">{titulo}</span>
                    <span className="wall__meta">
                      {evento.version ? `${evento.version} · ` : ""}
                      {evento.archivos} archivos · {formatBytes(evento.bytes_nuevos)}
                    </span>
                  </Link>
                );
              })}
            </div>

            <div className="band__foot">
              <span>
                {resumen
                  ? `${formatNumber(resumen.juegos_nuevos)} juegos nuevos · ${formatNumber(
                      resumen.actualizaciones,
                    )} con contenido nuevo`
                  : "Sin resumen disponible"}
              </span>
              <Link to="/novedades" className="band__cta">
                Ver todas ↗
              </Link>
            </div>
          </div>
          <BandEdge position="bottom" />
        </section>
      ) : null}

      <section className="retro-strip" aria-labelledby="retro-strip-title">
        <div className="retro-strip__inner">
          <div>
            <p
              className="mono-label"
              style={{ color: "#ffd6c8", marginBottom: "0.6rem" }}
            >
              Colección aparte · otro in-share
            </p>
            <h2 id="retro-strip-title">Retro</h2>
          </div>
          <div style={{ display: "grid", gap: "1rem", justifyItems: "start" }}>
            <p>
              {retroMeta
                ? `${formatNumber(retroMeta.titles)} juegos · ${retroMeta.buckets.length} sistemas · ${formatBytes(retroMeta.bytes)}`
                : "Arcade, consolas y microordenadores, con su propio volcado."}
            </p>
            <Link to="/retro" className="retro-strip__cta" data-cursor data-cursor-label="Entrar">
              Entrar al pasillo ↗
            </Link>
          </div>
        </div>
      </section>

      <SiteFooter meta={meta} sync={sync} />
    </>
  );
}
