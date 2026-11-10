import { Link } from "react-router";

/**
 * Cabecera fija del sitio: marca + secciones. Sin enlace a la API.
 */
export function SiteTop() {
  return (
    <header className="site-top" role="banner">
      <Link to="/" className="site-top__brand" aria-label="Alucardio DataBase — inicio">
        <span className="site-top__mark" aria-hidden="true" />
        <span>Alucardio</span>
      </Link>
      <span className="site-top__now">Biblioteca</span>
      <nav className="site-top__nav" aria-label="Secciones">
        <Link to="/novedades">Novedades ↗</Link>
        <Link to="/retro">Retro ↗</Link>
        <Link to="/actualizar" data-setup>
          Actualizar ↗
        </Link>
      </nav>
    </header>
  );
}
