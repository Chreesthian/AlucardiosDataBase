import type { ReactNode } from "react";

/**
 * Hero del catálogo: logotipo a sangre, blobs residentes y una línea discreta
 * con el recuento real. Se han retirado la cabecera mono (Switch · MEGA /
 * 2026), la tagline, la píldora y las métricas de almacenamiento.
 */
export function Hero({
  logo,
  meta,
}: {
  logo: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <section className="hero" aria-labelledby="page-title">
      {meta ? <div className="hero__counts">{meta}</div> : null}
      <div className="hero__body">
        <div className="hero__wordmark">
          <div className="hero__wordmark-inner">{logo}</div>
        </div>
        <span
          className="resident"
          aria-hidden="true"
          style={{
            width: 190,
            height: 190,
            right: "6%",
            top: "18%",
            ["--resident-color" as string]: "var(--surface-accent-1)",
          }}
        />
        <span
          className="resident"
          aria-hidden="true"
          style={{
            width: 130,
            height: 130,
            right: "16%",
            top: "52%",
            animationDelay: "-4s",
            ["--resident-color" as string]: "var(--surface-accent-3)",
          }}
        />
      </div>
    </section>
  );
}
