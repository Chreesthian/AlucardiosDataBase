import { useEffect, useState, type MouseEvent } from "react";
import type { LoaderFunctionArgs, MetaFunction } from "react-router";
import { data, Link, useLoaderData, useNavigate, useRouteLoaderData } from "react-router";

import { ImageLightbox, type LightboxImage } from "~/components/ImageLightbox";
import { SiteFooter } from "~/components/SiteFooter";
import { TapeTitle } from "~/components/TapeTitle";
import { api, type FichaIGDB, type TitleDetailOut } from "~/lib/api";
import {
  bannerUrl,
  coverUrl,
  difiereOficial,
  fechaLegible,
  first,
  formatBytes,
  formatNumber,
  initials,
  joinField,
  screenshotUrl,
} from "~/lib/format";

const TITULO_VERSION: Record<string, string> = {
  base: "VERSIÓN BASE",
  update: "ACTUALIZACIÓN",
  dlc: "DLC",
  other: "OTROS",
  carpeta: "CARPETA",
};

export const meta: MetaFunction<typeof loader> = ({ data: loaded }) => {
  const detail = loaded?.detail;
  if (!detail) return [{ title: "Juego no encontrado — Alucardio DataBase" }];
  const oficial = detail.igdb_name?.trim();
  return [
    { title: `${oficial || detail.name} — Alucardio DataBase` },
    {
      name: "description",
      content:
        detail.ficha?.descripcion?.slice(0, 240) ||
        detail.ficha?.argumento?.slice(0, 240) ||
        `${detail.name}: versiones, archivos y ficha IGDB en la biblioteca MEGA.`,
    },
  ];
};

export async function loader({ params }: LoaderFunctionArgs) {
  const slug = params.slug ?? "";
  try {
    const detail = await api.title(slug);
    return data({ detail, error: null }, { status: 200 });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = message.includes("API 404") ? 404 : 500;
    return data({ detail: null, error: message }, { status });
  }
}

export default function GameDetail() {
  const { detail, error } = useLoaderData<typeof loader>();
  const rootData = useRouteLoaderData("root") as
    | { apiPublicBase?: string }
    | undefined;

  if (!detail) {
    return (
      <section className="error-page">
        <p className="mono-label text-label">Ficha no disponible</p>
        <h1>No se pudo cargar el juego</h1>
        <p>{error}</p>
        <p>
          <Link to="/">← Volver a la biblioteca</Link>
        </p>
      </section>
    );
  }

  return (
    <DetailView
      detail={detail}
      apiPublicBase={rootData?.apiPublicBase ?? ""}
    />
  );
}

function asList(value: string[] | string | null | undefined): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => item.trim()).filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(/\s*[,·]\s*/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

export function DetailView({
  detail,
  apiPublicBase,
  priorizarCanonico = false,
  backTo = "/",
  backLabel = "Biblioteca",
}: {
  detail: TitleDetailOut;
  apiPublicBase: string;
  /** Retro: el nombre canónico de IGDB manda y la ROM real baja a subtítulo. */
  priorizarCanonico?: boolean;
  backTo?: string;
  backLabel?: string;
}) {
  const navigate = useNavigate();
  const volverALista = (event: MouseEvent<HTMLAnchorElement>) => {
    // Si venimos de una lista, retrocedemos en el historial: así se recupera
    // la URL (q/filtros) y ScrollRestoration devuelve la posición exacta.
    if (window.history.state?.idx > 0) {
      event.preventDefault();
      navigate(-1);
    }
  };
  const ficha: FichaIGDB | null = detail.ficha ?? null;
  const oficial =
    detail.igdb_name?.trim() || first(ficha?.nombre_oficial) || "";
  const mostrarOficial = difiereOficial(detail.name, oficial);
  const formats = detail.formats ?? [];
  const platform = detail.plataforma;
  const plataforma = platform?.nombre ?? first(ficha?.plataformas);
  const enRetro = priorizarCanonico && !!oficial;
  const tituloPrincipal = enRetro ? oficial : detail.name;
  const subtitulo = enRetro ? detail.name : mostrarOficial ? oficial : null;

  const descripcion = first(ficha?.descripcion);
  const argumento = first(ficha?.argumento);
  const release = first(ficha?.fecha_lanzamiento);
  const year = detail.igdb_year
    ? String(detail.igdb_year)
    : release
      ? release.slice(0, 4)
      : null;

  const generos = asList(ficha?.generos);
  const plataformas = asList(ficha?.plataformas);
  const temas = asList(ficha?.temas);
  const modos = asList(ficha?.modos);
  const perspectivas = asList(ficha?.perspectivas);
  const palabras = asList(ficha?.palabras_clave);
  const idiomas = asList(ficha?.idiomas_soporte);
  const capturas = asList(ficha?.capturas);
  const capturasVisibles = capturas.slice(0, 12);

  const clasificaciones = (ficha?.clasificaciones ?? [])
    .map((item) => item.texto?.trim())
    .filter((item): item is string => !!item);
  const clasificacion = clasificaciones.join(" · ");
  const pegi =
    first(ficha?.pegi) ||
    ficha?.clasificaciones?.find(
      (item) => item.sistema?.toUpperCase() === "PEGI",
    )?.texto?.trim() ||
    null;

  const rating = typeof ficha?.rating === "number" ? ficha.rating : null;
  const votes =
    typeof ficha?.votos_total === "number" ? ficha.votos_total : null;

  const cover = coverUrl(detail.igdb_cover || first(ficha?.caratula), "big");
  const hero = bannerUrl(first(ficha?.hero_imagen));
  const artwork = bannerUrl(first(ficha?.artworks));
  const shotBanner = screenshotUrl(first(ficha?.capturas), "full");
  const banner = hero ?? artwork ?? shotBanner ?? cover;
  const bannerIsCover = !!cover && banner === cover;

  const video = (ficha?.videos ?? []).find((item) => item.video_id);
  const enlaces: Array<{ etiqueta: string; url: string }> = [];
  for (const enlace of ficha?.enlaces ?? []) {
    const url = enlace.url?.trim();
    if (!url || enlaces.some((item) => item.url === url)) continue;
    enlaces.push({ etiqueta: enlace.etiqueta?.trim() || "Web", url });
  }

  const factRows: Array<[string, string]> = [];
  const pushFact = (label: string, value: unknown) => {
    const text = joinField(value);
    if (text) factRows.push([label, text]);
  };
  pushFact("Géneros", generos.join(" · "));
  pushFact("Plataformas", plataformas.join(" · "));
  pushFact("Modos", modos.join(" · "));
  pushFact("Temas", temas.join(" · "));
  pushFact("Perspectiva", perspectivas.join(" · "));
  pushFact("Clasificación", clasificacion);
  pushFact("Colección", ficha?.coleccion);
  pushFact("Franquicia", ficha?.franquicia);
  pushFact("Idiomas", idiomas.slice(0, 10).join(" · "));
  pushFact("Formatos", formats.join(" · "));
  pushFact("Tamaño", formatBytes(detail.size_bytes));
  pushFact(
    "Archivos",
    `${formatNumber(detail.file_count)} · ${detail.folder_count} carpetas`,
  );

  const lightboxImages: LightboxImage[] = [];
  const seenImages = new Set<string>();
  const addImage = (src: string | null, alt: string, caption: string) => {
    if (!src || seenImages.has(src)) return;
    seenImages.add(src);
    lightboxImages.push({ src, alt, caption });
  };
  addImage(banner, `Banner de ${tituloPrincipal}`, tituloPrincipal);
  addImage(
    cover,
    `Carátula de ${tituloPrincipal}`,
    `${tituloPrincipal} · carátula`,
  );
  capturas.forEach((src, index) => {
    const full = screenshotUrl(src, "full") ?? src;
    addImage(
      full,
      `Captura ${index + 1} de ${tituloPrincipal}`,
      `${tituloPrincipal} · captura ${index + 1}`,
    );
  });

  const [lightbox, setLightbox] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(false);
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, [detail.slug]);

  const openImage = (src?: string | null) => {
    if (!src) return;
    const index = lightboxImages.findIndex((image) => image.src === src);
    if (index >= 0) setLightbox(index);
  };

  return (
    <>
      <article
        className="detail-page"
        data-ready={ready ? "true" : "false"}
        data-testid="game-detail"
        style={{ paddingBottom: "var(--space-section)" }}
      >
        <div className="detail-banner-wrap">
          <div
            className={`detail-banner${bannerIsCover ? " detail-banner--cover" : ""}`}
            data-testid="detail-banner"
          >
            {banner ? (
              <button
                type="button"
                className="detail-banner__open"
                onClick={() => openImage(banner)}
                aria-label={`Ampliar banner de ${tituloPrincipal}`}
                data-cursor
                data-cursor-label="Ampliar"
              >
                <img
                  className="detail-banner__img"
                  src={banner}
                  alt=""
                  loading="eager"
                  fetchPriority="high"
                  decoding="async"
                  onError={(event) => {
                    (event.currentTarget as HTMLImageElement).style.opacity =
                      "0";
                  }}
                />
                <span className="detail-banner__veil" aria-hidden="true" />
                <span className="detail-banner__zoom" aria-hidden="true">
                  ⤢
                </span>
              </button>
            ) : (
              <div className="detail-banner__empty" aria-hidden="true">
                <span>{initials(tituloPrincipal)}</span>
              </div>
            )}

            <div className="detail-banner__bar page-shell">
              <Link
                to={backTo}
                className="back-link back-link--on-banner"
                onClick={volverALista}
              >
                ← {backLabel}
              </Link>
              <div className="detail-banner__tags">
                {plataforma ? <span>{plataforma}</span> : null}
                {year ? <span>{year}</span> : null}
                {rating !== null ? (
                  <span>
                    {Math.round(rating)}
                    <small>/100</small>
                  </span>
                ) : null}
                {pegi ? <span>{pegi}</span> : null}
              </div>
            </div>
          </div>
        </div>

        <div className="page-shell detail-body">
          <header className="detail-head">
            <p className="detail-eyebrow">
              {[plataforma, year, formats.join(" · ")]
                .filter(Boolean)
                .join("  ·  ")}
            </p>
            <TapeTitle>{tituloPrincipal}</TapeTitle>
            {subtitulo ? (
              <p
                className="detail-subtitle"
                title={
                  enRetro
                    ? "Nombre real del fichero (ROM en MEGA)"
                    : "Nombre canónico en IGDB"
                }
              >
                {enRetro ? "ROM" : "IGDB"} · {subtitulo}
              </p>
            ) : null}
            {ficha?.coleccion ? (
              <p className="detail-collection">{ficha.coleccion}</p>
            ) : null}
          </header>

          <div
            className="detail-lead"
            data-rise
            style={{ transitionDelay: "70ms" }}
          >
            <button
              type="button"
              className="detail-cover"
              onClick={() => openImage(cover)}
              aria-label={
                cover
                  ? `Ampliar carátula de ${tituloPrincipal}`
                  : "Carátula no disponible"
              }
              style={{ viewTransitionName: "game-cover" }}
              data-cursor
              data-cursor-label="Ampliar"
            >
              <span className="detail-cover__fallback" aria-hidden="true">
                {initials(tituloPrincipal)}
              </span>
              {cover ? (
                <img
                  src={cover}
                  alt={`Carátula de ${tituloPrincipal}`}
                  loading="eager"
                  decoding="async"
                  onError={(event) => {
                    (event.currentTarget as HTMLImageElement).style.display =
                      "none";
                  }}
                />
              ) : null}
              {cover ? (
                <span className="detail-cover__zoom" aria-hidden="true">
                  ⤢
                </span>
              ) : null}
            </button>

            <div className="detail-intro">
              <section
                className="detail-synopsis"
                aria-labelledby="synopsis-title"
                data-testid="detail-synopsis"
              >
                <h2
                  id="synopsis-title"
                  className="detail-section-label"
                >
                  <span>Sinopsis</span>
                  <span>IGDB</span>
                </h2>
                {descripcion ? (
                  <p className="detail-synopsis__text">{descripcion}</p>
                ) : (
                  <p className="detail-missing">
                    IGDB todavía no publica una sinopsis para este título.
                  </p>
                )}
                {argumento && argumento !== descripcion ? (
                  <p className="detail-synopsis__extra">{argumento}</p>
                ) : null}
              </section>

              <div className="detail-actions">
                {video?.video_id ? (
                  <a
                    className="detail-action detail-action--primary"
                    href={`https://www.youtube.com/watch?v=${encodeURIComponent(
                      video.video_id,
                    )}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    ▶ Ver tráiler
                  </a>
                ) : null}
                {ficha?.url_igdb ? (
                  <a
                    className="detail-action"
                    href={ficha.url_igdb}
                    target="_blank"
                    rel="noreferrer"
                  >
                    IGDB ↗
                  </a>
                ) : null}
                {enlaces.slice(0, 3).map((enlace) => (
                  <a
                    key={enlace.url}
                    className="detail-action"
                    href={enlace.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {enlace.etiqueta} ↗
                  </a>
                ))}
              </div>

              <dl className="detail-quickfacts">
                <div>
                  <dt>Lanzamiento</dt>
                  <dd>{release ? fechaLegible(release) : "—"}</dd>
                </div>
                <div>
                  <dt>Desarrollador</dt>
                  <dd>{first(ficha?.desarrollador) ?? "—"}</dd>
                </div>
                <div>
                  <dt>Editor</dt>
                  <dd>{first(ficha?.publicador) ?? "—"}</dd>
                </div>
                <div>
                  <dt>Valoración</dt>
                  <dd>
                    {rating !== null ? (
                      <>
                        {Math.round(rating)}
                        <span className="detail-quickfacts__small">/100</span>
                        {votes ? (
                          <span className="detail-quickfacts__votes">
                            {formatNumber(votes)} votos
                          </span>
                        ) : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          </div>

          <section
            className="detail-facts section-block"
            data-rise
            style={{ transitionDelay: "120ms" }}
            aria-labelledby="facts-title"
          >
            <h2
              id="facts-title"
              className="detail-section-label"
            >
              <span>Ficha técnica</span>
              <span>{ficha ? "IGDB + MEGA" : "MEGA"}</span>
            </h2>
            <dl className="detail-facts__grid">
              {factRows.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            {palabras.length ? (
              <div className="detail-keywords" aria-label="Palabras clave">
                {palabras.slice(0, 12).map((palabra) => (
                  <span key={palabra}>#{palabra}</span>
                ))}
              </div>
            ) : null}
          </section>

          {capturas.length ? (
            <section
              className="detail-gallery section-block"
              data-rise
              style={{ transitionDelay: "160ms" }}
              aria-labelledby="gallery-title"
            >
              <h2
                id="gallery-title"
                className="detail-section-label"
              >
                <span>Capturas</span>
                <span>
                  {capturasVisibles.length === capturas.length
                    ? capturas.length
                    : `${capturasVisibles.length} de ${capturas.length}`}{" "}
                  · IGDB
                </span>
              </h2>
              <div className="detail-shots">
                {capturasVisibles.map((src, index) => {
                  const thumb = screenshotUrl(src, "thumb") ?? src;
                  const full = screenshotUrl(src, "full") ?? src;
                  return (
                    <button
                      key={`${src}-${index}`}
                      type="button"
                      className="detail-shot"
                      data-testid="detail-shot"
                      onClick={() => openImage(full)}
                      aria-label={`Ampliar captura ${index + 1} de ${tituloPrincipal}`}
                      data-cursor
                      data-cursor-label="Ampliar"
                    >
                      <img
                        src={thumb}
                        alt={`Captura ${index + 1} de ${tituloPrincipal}`}
                        loading="lazy"
                        decoding="async"
                        onError={(event) => {
                          const shot = (
                            event.currentTarget as HTMLImageElement
                          ).closest(".detail-shot");
                          if (shot instanceof HTMLElement) {
                            shot.style.display = "none";
                          }
                        }}
                      />
                      <span className="detail-shot__zoom" aria-hidden="true">
                        ⤢
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          ) : null}

          <section
            className="detail-versions section-block"
            data-rise
            style={{ transitionDelay: "200ms" }}
            aria-labelledby="versions-title"
          >
            <h2
              id="versions-title"
              className="detail-section-label"
              aria-label="Versiones"
            >
              <span>Versiones y archivos</span>
              <span>
                {detail.versions.length} carpetas ·{" "}
                {formatNumber(detail.file_count)} archivos
              </span>
            </h2>

            <div className="detail-versions__list">
              {detail.versions.map((version) => (
                <details
                  className="version"
                  key={version.id}
                  open={version.label === "base"}
                >
                  <summary className="version__head">
                    <span className="version__label">
                      {TITULO_VERSION[version.label] ?? version.name}
                    </span>
                    <span className="version__name">{version.name}</span>
                    <span className="version__meta">
                      {formatBytes(version.size_bytes)} · {version.file_count}{" "}
                      archivos
                    </span>
                    <span className="version__chevron" aria-hidden="true">
                      ⌄
                    </span>
                  </summary>
                  <div className="version__body">
                    {version.full_path ? (
                      <a
                        className="dl dl--folder"
                        data-download
                        href={`${apiPublicBase}/api/download?path=${encodeURIComponent(
                          version.full_path,
                        )}`}
                        rel="noreferrer"
                        title="Descargar esta carpeta desde MEGA"
                      >
                        ⬇ descargar carpeta
                      </a>
                    ) : null}
                    {version.files.length ? (
                      <ul className="file-list">
                        {version.files.map((file) => (
                          <li key={`${version.id}-${file.path}`}>
                            <span>{file.name}</span>
                            <span className="file-list__actions">
                              <span>{formatBytes(file.size)}</span>
                              {file.full_path ? (
                                <a
                                  className="dl"
                                  data-download
                                  href={`${apiPublicBase}/api/download?path=${encodeURIComponent(
                                    file.full_path,
                                  )}`}
                                  rel="noreferrer"
                                  title={`Descargar ${file.name} desde MEGA`}
                                >
                                  ⬇
                                </a>
                              ) : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="detail-missing">Sin archivos listados.</p>
                    )}
                  </div>
                </details>
              ))}

              {detail.remaining_files.length ? (
                <details className="version" open>
                  <summary className="version__head">
                    <span className="version__label">SUELTOS</span>
                    <span className="version__name">archivos sin versión</span>
                    <span className="version__meta">
                      {detail.remaining_files.length} archivos
                    </span>
                    <span className="version__chevron" aria-hidden="true">
                      ⌄
                    </span>
                  </summary>
                  <div className="version__body">
                    <ul className="file-list">
                      {detail.remaining_files.map((file) => (
                        <li key={`r-${file.path}`}>
                          <span>{file.name}</span>
                          <span className="file-list__actions">
                            <span>{formatBytes(file.size)}</span>
                            {file.full_path ? (
                              <a
                                className="dl"
                                data-download
                                href={`${apiPublicBase}/api/download?path=${encodeURIComponent(
                                  file.full_path,
                                )}`}
                                rel="noreferrer"
                                title={`Descargar ${file.name} desde MEGA`}
                              >
                                ⬇
                              </a>
                            ) : null}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </details>
              ) : null}
            </div>
          </section>
        </div>

        <ImageLightbox
          images={lightboxImages}
          index={lightbox}
          onClose={() => setLightbox(null)}
          onIndex={(next) => setLightbox(next)}
        />
      </article>

      <SiteFooter meta={null} sync={null} />
    </>
  );
}
