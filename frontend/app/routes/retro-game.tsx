import type { LoaderFunctionArgs, MetaFunction } from "react-router";
import { data, Link, useLoaderData, useRouteLoaderData } from "react-router";

import { api } from "~/lib/api";
import { DetailView } from "./game";

export const meta: MetaFunction<typeof loader> = ({ data: loaded }) => {
  const detail = loaded?.detail;
  if (!detail) return [{ title: "ROM no encontrada — AlucardiosDataBase" }];
  return [
    {
      title: `${detail.igdb_name?.trim() || detail.name} — Retro · AlucardiosDataBase`,
    },
  ];
};

export async function loader({ params }: LoaderFunctionArgs) {
  const slug = params.slug ?? "";
  try {
    const detail = await api.retroTitle(slug);
    return data({ detail, error: null }, { status: 200 });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = message.includes("API 404") ? 404 : 500;
    return data({ detail: null, error: message }, { status });
  }
}

export default function RetroGame() {
  const { detail, error } = useLoaderData<typeof loader>();
  const rootData = useRouteLoaderData("root") as
    | { apiPublicBase?: string }
    | undefined;

  if (!detail) {
    return (
      <section className="error-page">
        <p className="mono-label text-label">ROM no disponible</p>
        <h1>No se pudo cargar el juego</h1>
        <p>{error}</p>
        <p>
          <Link to="/retro">← Volver a retro</Link>
        </p>
      </section>
    );
  }

  return (
    <DetailView
      detail={detail}
      apiPublicBase={rootData?.apiPublicBase ?? ""}
      priorizarCanonico
      backTo="/retro"
      backLabel="Retro"
    />
  );
}
