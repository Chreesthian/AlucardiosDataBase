import { Link } from "react-router";
import type { GameViewItem } from "~/lib/game-view";
import { coverUrl, initials, rowIndex } from "~/lib/format";

/**
 * Panel sticky compartido por las tres secciones. Recibe el modelo común
 * `GameViewItem`, así que Biblioteca, Retro y Novedades enseñan exactamente la
 * misma ficha (carátula, nombre canónico/real, datos y acciones).
 */
export function GamePanel({ item, index }: { item: GameViewItem; index: number }) {
  return (
    <div className="work-panel__inner">
      <p className="work-panel__eyebrow">
        {rowIndex(index)} · {item.eyebrow}
      </p>

      <div className="work-panel__cover">
        <span className="work-panel__cover-fallback" aria-hidden="true">
          {initials(item.name)}
        </span>
        {item.cover ? (
          <img
            src={coverUrl(item.cover, "big") ?? item.cover}
            alt={item.name}
            loading="lazy"
            decoding="async"
            onError={(event) => {
              (event.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : null}
      </div>

      <h3 className="work-panel__title">{item.name}</h3>
      {item.subtitle ? (
        <p
          className="work-panel__real"
          title={item.subtitleLabel === "ROM" ? "Nombre real del fichero (ROM en MEGA)" : "Nombre canónico en IGDB"}
        >
          {item.subtitleLabel ?? "IGDB"} · {item.subtitle}
        </p>
      ) : null}
      {item.description ? <p className="work-panel__text">{item.description}</p> : null}

      <dl className="work-panel__facts">
        {item.facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      <div className="tag-row">
        {item.tags.map((tag) => (
          <span className="tag" key={tag}>
            {tag}
          </span>
        ))}
      </div>

      <div className="panel-actions">
        <Link
          to={item.href}
          data-cursor
          data-cursor-label="Ver ficha"
          viewTransition
        >
          Explorar ficha →
        </Link>
      </div>
    </div>
  );
}
