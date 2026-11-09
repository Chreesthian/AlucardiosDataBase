import { useState } from "react";
import { Link } from "react-router";
import type { MetaOut, SyncStatusOut } from "~/lib/api";
import { edadLegible, formatNumber } from "~/lib/format";

/**
 * Cierre del sitio: estado del catálogo + drain carmesí con la chapa circular.
 */
export function SiteFooter({
  meta,
  sync,
}: {
  meta: MetaOut | null;
  sync: SyncStatusOut | null;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText("alucard.db");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* portapapeles no disponible */
    }
  };

  const edad = sync?.dump_age_hours ?? null;

  return (
    <>
      <section className="contact section" aria-label="Estado">
        <div>
          <p className="contact__say">Estado</p>
          <div className="contact__mail">
            <code>alucard.db</code>
            <button
              type="button"
              className="contact__copy"
              onClick={copy}
              data-cursor
              data-cursor-label="Copiar"
            >
              {copied ? "Copiado" : "Copiar"}
            </button>
          </div>
          <p className="contact__note">
            {meta
              ? `${formatNumber(meta.titles)} juegos · ${formatNumber(meta.files)} archivos.`
              : "Ficha servida directamente desde el catálogo (alucard.db)."}{" "}
            {sync ? `Actualizado hace ${edadLegible(edad)}.` : null}
          </p>
          <div className="contact__links">
            <Link to="/novedades">Novedades ↗</Link>
            <Link to="/retro">Retro ↗</Link>
          </div>
        </div>

        <div className="drain">
          <a className="drain__badge" href="#top" aria-label="Volver arriba">
            <svg viewBox="0 0 200 200" aria-hidden="true">
              <defs>
                <path
                  id="badge-ring"
                  d="M100,100 m-76,0 a76,76 0 1,1 152,0 a76,76 0 1,1 -152,0"
                />
              </defs>
              <text className="drain__badge-text">
                <textPath href="#badge-ring" startOffset="0">
                  Vuelve arriba · © Alucardios · Todo lo que tienes, en un sitio ·
                </textPath>
              </text>
              <text x="100" y="120" textAnchor="middle" className="drain__badge-arrow">
                ↑
              </text>
            </svg>
          </a>
          <div className="drain__links">
            <Link to="/novedades">Novedades ↗</Link>
            <Link to="/retro">Retro ↗</Link>
            <a href="#top">↑ Top</a>
          </div>
        </div>
      </section>
    </>
  );
}
