import type { ReactNode } from "react";
import type { LinksFunction, LoaderFunctionArgs, MetaFunction } from "react-router";
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
  useLoaderData,
  useLocation,
  useRouteError,
} from "react-router";

import stylesheet from "~/styles/app.css?url";
import { Cursor } from "~/components/Cursor";
import { MoodDock } from "~/components/MoodDock";
import { ScrollTopAnchor } from "~/components/ScrollTopAnchor";
import { SiteTop } from "~/components/SiteTop";
import { useRevealOnScroll } from "~/lib/hooks";

export const links: LinksFunction = () => [
  { rel: "stylesheet", href: stylesheet, precedence: "default" },
  { rel: "manifest", href: "/manifest.webmanifest" },
  { rel: "icon", type: "image/png", href: "/icons/icon-192.png" },
  { rel: "icon", type: "image/svg+xml", href: "/favicon.svg" },
  { rel: "apple-touch-icon", href: "/icons/apple-touch-icon.png" },
  { rel: "preconnect", href: "https://images.igdb.com" },
];

export const meta: MetaFunction = () => [
  { title: "La biblioteca de Alucardio — Alucardio DataBase" },
  {
    name: "description",
    content:
      "Catálogo navegable de la biblioteca de juegos de Switch en MEGA, con portadas y fichas de IGDB.",
  },
  { name: "theme-color", content: "#111314" },
  { property: "og:type", content: "website" },
  { property: "og:title", content: "La biblioteca de Alucardio — Alucardio DataBase" },
  {
    property: "og:description",
    content: "Todo lo que vive en tu cuenta MEGA, en un solo sitio.",
  },
];

export async function loader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  const publicPort = process.env.ALUCARD_PUBLIC_BACKEND_PORT ?? "7331";
  const proto = request.headers.get("x-forwarded-proto") ?? url.protocol.replace(":", "");
  const apiPublicBase = `${proto}://${url.hostname}:${publicPort}`;
  return { apiPublicBase, publicPort };
}

/** Se ejecuta antes del primer pintado: tinta guardada + URL pública de la API. */
function bootstrap(publicPort: string) {
  return `(function(){
  try {
    var ink = localStorage.getItem("alucard:ink");
    var ok = ["dusk","night","day","morning"];
    if (ink && ok.indexOf(ink) > -1) document.documentElement.dataset.ink = ink;
  } catch (e) {}
  window.__ALUCARD_API = location.protocol + "//" + location.hostname + ":" + ${JSON.stringify(publicPort)};
  if ("serviceWorker" in navigator && /^https?:$/.test(location.protocol)) {
    addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }
})();`;
}

export function Layout({ children }: { children: ReactNode }) {
  const data = useLoaderData<typeof loader>();
  const location = useLocation();
  useRevealOnScroll(`${location.pathname}${location.search}`);

  return (
    <html lang="es" data-theme="house" data-house="classic" data-ink="dusk">
      <head>
        <meta charSet="utf-8" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1.0, viewport-fit=cover"
        />
        <Meta />
        <Links />
        <noscript>
          <style>{`.reveal{opacity:1;translate:none;filter:none}`}</style>
        </noscript>
        <script dangerouslySetInnerHTML={{ __html: bootstrap(data.publicPort) }} />
      </head>
      <body>
        <span id="top" aria-hidden="true" />
        <SiteTop />
        <main className="main-shell">{children}</main>
        <MoodDock />
        <ScrollTopAnchor />
        <Cursor />
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return <Outlet />;
}

export function ErrorBoundary() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;

  return (
    <section className="error-page">
      <p className="mono-label text-label">{notFound ? "404 · fuera de catálogo" : "Error"}</p>
      <h1>{notFound ? "No se pudo cargar el juego" : "Algo se rompió"}</h1>
      <p>
        {notFound
          ? "Ese título no existe en la biblioteca (o cambió de nombre en el último volcado)."
          : "La API no respondió como esperaba. Revisa el backend en :7331."}
      </p>
      <p>
        <a href="/">← Volver a la biblioteca</a>
      </p>
      {!notFound ? (
        <pre>{error instanceof Error ? error.message : String(error)}</pre>
      ) : null}
    </section>
  );
}
