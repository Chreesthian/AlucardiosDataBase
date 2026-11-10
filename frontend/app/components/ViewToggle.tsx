import { Link } from "react-router";
import type { ViewMode } from "~/lib/game-view";

/**
 * Conmutador lista/cuadrícula. Son enlaces reales (`?vista=`), así que la vista
 * se renderiza en SSR, es compartible y sobrevive a recargas y paginación.
 */
export function ViewToggle({
  view,
  listHref,
  gridHref,
}: {
  view: ViewMode;
  listHref: string;
  gridHref: string;
}) {
  return (
    <div className="view-toggle" role="group" aria-label="Forma de mostrar los juegos">
      <Link
        to={listHref}
        className="view-toggle__btn"
        data-active={view === "lista"}
        aria-current={view === "lista" ? "page" : undefined}
        title="Ver como lista"
        preventScrollReset
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M2 3.5h12M2 8h12M2 12.5h12" />
        </svg>
        Lista
      </Link>
      <Link
        to={gridHref}
        className="view-toggle__btn"
        data-active={view === "cuadricula"}
        aria-current={view === "cuadricula" ? "page" : undefined}
        title="Ver como cuadrícula"
        preventScrollReset
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M2.5 2.5h4v4h-4zM9.5 2.5h4v4h-4zM2.5 9.5h4v4h-4zM9.5 9.5h4v4h-4z" />
        </svg>
        Cuadrícula
      </Link>
    </div>
  );
}
