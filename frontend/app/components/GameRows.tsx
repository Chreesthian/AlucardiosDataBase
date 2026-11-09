import { useState, type CSSProperties } from "react";
import { flushSync } from "react-dom";
import { Link } from "react-router";
import type { GameViewItem } from "~/lib/game-view";
import { rowIndex } from "~/lib/format";
import { GamePanel } from "./GamePanel";

/**
 * Filas tipográficas gigantes con panel sticky. Es la vista POR DEFECTO de las
 * tres secciones. Cada fila es `<a href=… title=…>` para conservar el contrato
 * de la auditoría (`main a[href^="/game/"][title]`).
 */
export function GameRows({
  items,
  offset,
  panel = true,
}: {
  items: GameViewItem[];
  offset: number;
  panel?: boolean;
}) {
  const [active, setActive] = useState(0);

  if (!items.length) {
    return (
      <div className="empty-state">
        Sin resultados. Prueba otra búsqueda, otra letra u otro orden.
      </div>
    );
  }

  const activeIndex = Math.min(active, items.length - 1);
  const current = items[activeIndex];

  return (
    <div className={panel ? "work-grid" : "work-grid work-grid--no-panel"}>
      <ol className="work-list">
        {items.map((item, index) => {
          const accent = `var(--surface-accent-${(index % 4) + 1})`;
          return (
            <li key={item.key}>
              <Link
                to={item.href}
                title={item.titleAttr}
                className="work-row"
                data-active={index === activeIndex}
                data-case-row={item.key}
                data-cursor
                data-cursor-label="Abrir ficha"
                style={{ "--row-accent": accent } as CSSProperties}
                viewTransition
                onPointerDown={() =>
                  flushSync(() => setActive(index))
                }
                onMouseEnter={() => setActive(index)}
                onFocus={() => setActive(index)}
              >
                <span className="work-row__left">
                  <span className="work-row__index">{rowIndex(offset + index + 1)}</span>
                  <span
                    className="work-row__name"
                    data-motion="name"
                    style={
                      index === activeIndex
                        ? { viewTransitionName: "game-title" }
                        : undefined
                    }
                  >
                    {item.name}
                  </span>
                </span>
                <span className="work-row__right">
                  <span>{item.eventLabel ?? item.year ?? "—"}</span>
                  <span>
                    <b>{item.platform ?? "—"}</b>
                    {item.formats.length ? ` · ${item.formats.slice(0, 3).join(" · ")}` : ""}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>

      {panel ? (
        <aside className="work-panel" aria-live="polite">
          <GamePanel item={current} index={offset + activeIndex + 1} />
        </aside>
      ) : null}
    </div>
  );
}
