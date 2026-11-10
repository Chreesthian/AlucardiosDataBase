import { useState } from "react";
import { flushSync } from "react-dom";
import { CoverCard } from "./CoverCard";
import type { GameViewItem } from "~/lib/game-view";

/** Rejilla de carátulas compartida por las tres secciones. */
export function GameGrid({ items }: { items: GameViewItem[] }) {
  const [picked, setPicked] = useState<string | null>(null);

  if (!items.length) {
    return (
      <div className="empty-state">
        Sin resultados. Prueba otra búsqueda, otra letra u otro orden.
      </div>
    );
  }

  return (
    <div className="cover-grid">
      {items.map((item) => (
        <CoverCard
          key={item.key}
          href={item.href}
          name={item.name}
          cover={item.cover}
          badge={item.badge}
          meta={item.gridMeta}
          titleAttr={item.titleAttr}
          share={picked === item.key}
          selected={picked === item.key}
          onPointerDown={() => flushSync(() => setPicked(item.key))}
          onFocus={() => setPicked(item.key)}
        />
      ))}
    </div>
  );
}
