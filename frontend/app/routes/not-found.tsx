import { Link } from "react-router";

export default function NotFound() {
  return (
    <section className="error-page">
      <p className="mono-label text-label">404 · fuera de catálogo</p>
      <h1>Esa página no existe.</h1>
      <p>Puede que el enlace haya cambiado de nombre en el último volcado.</p>
      <p>
        <Link to="/">← Volver a la biblioteca</Link>
      </p>
    </section>
  );
}
