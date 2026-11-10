/**
 * Wordmark tipográfico del sitio. El original usa un SVG dibujado a mano con
 * dos líneas apiladas; aquí se reproduce el mismo bloque condensado con la
 * fuente display y `textLength` (spacingAndGlyphs) para estirar/condensar las
 * letras exactamente al ancho del contenedor.
 */
export function Wordmark({
  lines = ["LA BIBLIOTECA", "DE ALUCARDIO"],
  className = "",
}: {
  lines?: [string, string];
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 1000 560"
      role="img"
      aria-labelledby="wordmark-title"
      className={`wordmark-svg ${className}`.trim()}
    >
      <title id="wordmark-title">La biblioteca de Alucardio</title>
      <text
        x="500"
        y="248"
        textAnchor="middle"
        textLength="970"
        lengthAdjust="spacingAndGlyphs"
        fontSize="330"
      >
        {lines[0]}
      </text>
      <text
        x="500"
        y="524"
        textAnchor="middle"
        textLength="970"
        lengthAdjust="spacingAndGlyphs"
        fontSize="330"
      >
        {lines[1]}
      </text>
    </svg>
  );
}
