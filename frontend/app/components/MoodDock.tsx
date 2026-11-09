import { useInk } from "~/lib/hooks";

/**
 * "CHANGE THE MOOD" del original: píldora + botón circular. Cambia la tinta
 * de la casa (dusk → night → day → morning) y la persiste en localStorage.
 */
export function MoodDock() {
  const { ink, cycle } = useInk();

  return (
    <div className="mood-dock">
      <span className="mood-dock__label">Cambiar el ánimo</span>
      <button
        type="button"
        className="mood-dock__button"
        onClick={cycle}
        aria-label={`Cambiar el ánimo (ahora: ${ink})`}
        title={`Ánimo: ${ink}`}
        data-cursor
        data-cursor-label="Cambiar"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" fill="currentColor" />
          <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M12 2.4v2.2M12 19.4v2.2M2.4 12h2.2M19.4 12h2.2" />
            <path d="M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6" />
          </g>
        </svg>
      </button>
    </div>
  );
}
