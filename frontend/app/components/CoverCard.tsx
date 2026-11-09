import { Link } from "react-router";
import { coverUrl, initials } from "~/lib/format";

/** Tarjeta de carátula compartida por las tres secciones (vista cuadrícula). */
export function CoverCard({
  href,
  name,
  cover,
  badge,
  meta,
  titleAttr,
  share = false,
  onPointerDown,
  onFocus,
}: {
  href: string;
  name: string;
  cover?: string | null;
  badge?: string | null;
  meta?: string | null;
  titleAttr?: string | null;
  share?: boolean;
  onPointerDown?: () => void;
  onFocus?: () => void;
}) {
  return (
    <Link
      to={href}
      className="cover-card"
      title={titleAttr ?? name}
      data-cursor
      data-cursor-label="Abrir ficha"
      viewTransition
      onPointerDown={onPointerDown}
      onFocus={onFocus}
    >
      <div
        className="cover-card__art"
        style={share ? { viewTransitionName: "game-cover" } : undefined}
      >
        {badge ? <span className="cover-card__badge">{badge}</span> : null}
        <span className="cover-card__fallback" aria-hidden="true">
          {initials(name)}
        </span>
        {cover ? (
          <img
            src={coverUrl(cover, "grid") ?? cover}
            alt={name}
            loading="lazy"
            decoding="async"
            onError={(event) => {
              (event.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : null}
      </div>
      <div
        className="cover-card__title"
        data-motion="name"
        style={share ? { viewTransitionName: "game-title" } : undefined}
      >
        {name}
      </div>
      {meta ? <div className="cover-card__meta">{meta}</div> : null}
    </Link>
  );
}
