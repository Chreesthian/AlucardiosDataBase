import { useEffect, useRef, type CSSProperties } from "react";

/**
 * Título “tape” reconstruido del caso de estudio de charbeltannous.com:
 * cada letra lleva un trozo de cinta con clip-path irregular y alterna
 * entre los cinco colores de tape; al pasar el cursor intercambia relleno.
 * La referencia usa una columna de letras; aquí se adapta a palabras
 * horizontales para que títulos largos sigan siendo legibles.
 */
const TAPE_CLIPS = [
  "polygon(0 6%, 100% 0, 99.2% 100%, 0.8% 94%)",
  "polygon(0.6% 0, 99.4% 5%, 100% 96%, 0 100%)",
  "polygon(0 0, 99.3% 3%, 100% 100%, 0.5% 95%)",
] as const;

const TAPE_FILLS = 5;

function seedFromString(value: string): number {
  let hash = 0;
  for (const char of value) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return hash % TAPE_FILLS;
}

export function TapeTitle({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  const seed = seedFromString(children);
  let letterIndex = 0;
  const titleRef = useRef<HTMLHeadingElement>(null);

  // Equivalente a data-route-focus del original: al entrar en una ficha el
  // foco va al título sin provocar scroll; el lector de pantalla lo anuncia.
  useEffect(() => {
    titleRef.current?.focus({ preventScroll: true });
  }, [children]);

  return (
    <h1
      ref={titleRef}
      className={`detail-title${className ? ` ${className}` : ""}`}
      aria-label={children}
      tabIndex={-1}
      style={{ viewTransitionName: "game-title" }}
    >
      <span className="detail-title__tape" aria-hidden="true">
        {children.split(/(\s+)/).map((word, wordIndex) => {
          if (!word.trim()) {
            return (
              <span
                key={`space-${wordIndex}`}
                className="detail-title__space"
              >
                {" "}
              </span>
            );
          }

          return (
            <span className="detail-title__word" key={`word-${wordIndex}`}>
              {[...word].map((char, charIndex) => {
                const index = letterIndex++;
                const restIndex = (index + seed * 2) % TAPE_FILLS;
                const rawHover = (index * 3 + seed + 2) % TAPE_FILLS;
                const hoverIndex =
                  rawHover === restIndex
                    ? (restIndex + 1) % TAPE_FILLS
                    : rawHover;
                const outline = index % 4 === 2;

                return (
                  <span
                    key={`char-${wordIndex}-${charIndex}`}
                    className={`tape-letter${outline ? " tape-letter--outline" : ""}`}
                    style={
                      {
                        "--rest": `var(--tape-fill-${restIndex + 1})`,
                        "--hover": `var(--tape-fill-${hoverIndex + 1})`,
                        "--letter-i": index,
                        clipPath:
                          TAPE_CLIPS[(seed + wordIndex + index) % TAPE_CLIPS.length],
                      } as CSSProperties
                    }
                  >
                    {char}
                  </span>
                );
              })}
            </span>
          );
        })}
      </span>
    </h1>
  );
}
