import type { LoaderFunctionArgs, MetaFunction } from "react-router";
import { Link, useLoaderData } from "react-router";

import { GameGrid } from "~/components/GameGrid";
import { GameRows } from "~/components/GameRows";
import { SiteFooter } from "~/components/SiteFooter";
import { ViewToggle } from "~/components/ViewToggle";
import { api } from "~/lib/api";
import { eventItem, parseView, VIEW_PARAM } from "~/lib/game-view";
import { edadLegible, formatNumber } from "~/lib/format";

export const meta: MetaFunction = () => [
  { title: "Novedades — AlucardiosDataBase" },
  {
    name: "description",
    content:
      "Juegos nuevos y archivos nuevos de actualización y DLC en la biblioteca MEGA.",
  },
];

export async function loader({ request }: LoaderFunctionArgs) {
  const view = parseView(new URL(request.url).searchParams.get(VIEW_PARAM));
  const [juegos, contenido, estado] = await Promise.all([
    api.novedades({ tipo: "juego_nuevo", limit: 120 }).catch(() => null),
    api
      .novedades({ tipo: "update_nuevo,dlc_nuevo,contenido_nuevo", limit: 120 })
      .catch(() => null),
    api.syncStatus().catch(() => null),
  ]);

  return {
    view,
    juegos,
    contenido,
    estado,
    error: juegos || contenido ? null : "No se pudo consultar /api/novedades.",
  };
}

export default function Novedades() {
  const { view, juegos, contenido, estado, error } =
    useLoaderData<typeof loader>();

  const resumen = juegos?.resumen ?? contenido?.resumen ?? null;
  const nuevos = juegos?.items ?? [];
  const actualizados = contenido?.items ?? [];

  const nuevosItems = nuevos.map((evento, index) =>
    eventItem(evento, { href: `/game/${evento.slug}/`, index }),
  );
  const contenidoItems = actualizados.map((evento, index) =>
    eventItem(evento, { href: `/game/${evento.slug}/`, index }),
  );

  const listHref = "/novedades";
  const gridHref = `/novedades?${VIEW_PARAM}=cuadricula`;

  return (
    <>
      <section className="page-head page-shell">
        <p className="page-head__eyebrow">
          <Link to="/" className="back-link" style={{ minHeight: "auto" }}>
            ← Biblioteca
          </Link>
          <span>Recién llegados</span>
        </p>
        <h1 className="page-head__title">Lo último que ha entrado.</h1>
        <p className="page-head__note">
          Juegos completos nuevos y títulos que han recibido archivos nuevos de
          actualización o DLC. Se actualiza automáticamente con cada incorporación
          a la biblioteca.
        </p>
        <div className="page-head__stats">
          <span>
            <b>{resumen ? formatNumber(resumen.juegos_nuevos) : "—"}</b> juegos nuevos
          </span>
          <span>
            <b>{resumen ? formatNumber(resumen.actualizaciones) : "—"}</b> con contenido nuevo
          </span>
          <span>
            Actualizado <b>{estado ? `hace ${edadLegible(estado.dump_age_hours)}` : "—"}</b>
          </span>
        </div>
      </section>

      {error ? (
        <div className="page-shell">
          <div className="empty-state">{error}</div>
        </div>
      ) : null}

      <div className="page-shell" style={{ paddingBottom: "0.75rem" }}>
        <div className="view-bar">
          <span className="view-bar__count">
            {nuevos.length + actualizados.length} eventos
          </span>
          <ViewToggle view={view} listHref={listHref} gridHref={gridHref} />
        </div>
      </div>

      {nuevos.length ? (
        <section
          className="page-shell section"
          style={{ paddingTop: 0 }}
          aria-labelledby="nuevos-title"
        >
          <div className="section-block__head">
            <h2 id="nuevos-title" className="section-block__title">
              Juegos nuevos
            </h2>
            <span className="section-block__count">{nuevos.length} eventos</span>
          </div>
          {view === "cuadricula" ? (
            <GameGrid items={nuevosItems} />
          ) : (
            <GameRows items={nuevosItems} offset={0} />
          )}
        </section>
      ) : null}

      {actualizados.length ? (
        <section className="page-shell" aria-labelledby="contenido-title">
          <div className="section-block__head">
            <h2 id="contenido-title" className="section-block__title">
              Contenido nuevo
            </h2>
            <span className="section-block__count">{actualizados.length} eventos</span>
          </div>
          {view === "cuadricula" ? (
            <GameGrid items={contenidoItems} />
          ) : (
            <GameRows items={contenidoItems} offset={0} />
          )}
        </section>
      ) : null}

      {!nuevos.length && !actualizados.length && !error ? (
        <div className="page-shell">
          <div className="empty-state">
            Todavía no hay eventos: el próximo escaneo con contenido nuevo los creará.
          </div>
        </div>
      ) : null}

      <SiteFooter meta={null} sync={estado} />
    </>
  );
}
