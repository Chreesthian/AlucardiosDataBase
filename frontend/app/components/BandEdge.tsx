/**
 * Borde "goo" entre una banda y la página: copia el recurso del sitio original
 * (rect + círculos con blur y feColorMatrix) para que la banda parezca tinta
 * derramada sobre el fondo.
 */
const BLOBS = [
  [-60, 104, 64],
  [89, 116, 25],
  [218, 109, 51],
  [397, 114, 33],
  [540, 113, 36],
  [674, 113, 38],
  [812, 105, 62],
  [979, 108, 53],
  [1158, 107, 57],
  [1294, 108, 52],
  [1444, 116, 25],
  [1618, 106, 59],
  [1746, 107, 58],
  [1903, 108, 53],
  [2073, 115, 30],
  [2212, 108, 54],
  [2386, 114, 32],
] as const;

export function BandEdge({ position }: { position: "top" | "bottom" }) {
  const id = `band-goo-${position}`;
  return (
    <div className={`band-edge band-edge--${position}`} aria-hidden="true">
      <svg viewBox="0 0 2400 120" preserveAspectRatio="xMidYMax slice">
        <filter id={id} x="-5%" y="-50%" width="110%" height="200%" colorInterpolationFilters="sRGB">
          <feGaussianBlur stdDeviation="11" />
          <feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 24 -11" />
        </filter>
        <g filter={`url(#${id})`} fill="currentColor">
          <rect x="-100" y="104" width="2600" height="120" />
          {BLOBS.map(([cx, cy, r]) => (
            <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} />
          ))}
        </g>
      </svg>
    </div>
  );
}
