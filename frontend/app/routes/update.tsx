import { useEffect, useState, type FormEvent } from "react";
import type { MetaFunction } from "react-router";
import { Link, useLoaderData, useRevalidator } from "react-router";

import { SiteFooter } from "~/components/SiteFooter";
import {
  api,
  type MegaCuentaIn,
  type MegaSetupOut,
  type MetaOut,
  type SyncStatusOut,
} from "~/lib/api";
import { edadLegible, formatNumber } from "~/lib/format";

export const meta: MetaFunction = () => [
  { title: "Actualizar biblioteca — La Biblioteca de Alucardio" },
  {
    name: "description",
    content:
      "Conecta las tres cuentas MEGA y actualiza la biblioteca desde la propia interfaz.",
  },
];

export async function loader() {
  try {
    const [setup, meta, sync] = await Promise.all([
      api.megaSetup(),
      api.meta().catch(() => null),
      api.syncStatus().catch(() => null),
    ]);
    return { setup, meta, sync, error: null };
  } catch (error) {
    return {
      setup: null,
      meta: null,
      sync: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

const PASOS = [
  { key: "guardando", label: "Preparando" },
  { key: "verificando", label: "Comprobando cuentas" },
  { key: "volcando", label: "Descargando catálogo" },
  { key: "sincronizando", label: "Aplicando cambios" },
] as const;

function mensajeHumano(error: unknown): string {
  const texto = error instanceof Error ? error.message : String(error);
  return (
    texto.replace(/^API \d+:[^ ]*\s*/, "").trim() ||
    "No se pudo completar la operación. Inténtalo de nuevo."
  );
}

function numero(resumen: Record<string, unknown> | null, clave: string): number {
  const valor = resumen?.[clave];
  return typeof valor === "number" ? valor : 0;
}

export default function Actualizar() {
  const { setup: inicial, meta, sync, error: errorCarga } = useLoaderData<typeof loader>();
  const revalidator = useRevalidator();
  const [setup, setSetup] = useState<MegaSetupOut | null>(inicial);
  const [emails, setEmails] = useState<string[]>(() =>
    [0, 1, 2].map((indice) => inicial?.cuentas[indice]?.email ?? ""),
  );
  const [passwords, setPasswords] = useState<string[]>(["", "", ""]);
  const [visibles, setVisibles] = useState<boolean[]>([false, false, false]);
  const [busy, setBusy] = useState(
    inicial?.actualizacion.estado === "en_curso",
  );
  const [error, setError] = useState<string | null>(null);

  const configurado = (setup?.cuentas.length ?? 0) > 0;

  useEffect(() => {
    if (!setup?.disponible || setup.actualizacion.estado !== "en_curso") return;
    let cancelado = false;
    const tick = async () => {
      try {
        const siguiente = await api.megaSetup();
        if (cancelado) return;
        setSetup(siguiente);
        if (siguiente.actualizacion.estado !== "en_curso") {
          setBusy(false);
          revalidator.revalidate();
        }
      } catch {
        /* La siguiente vuelta reintenta; no se pierde el estado local. */
      }
    };
    const id = window.setInterval(tick, 2000);
    return () => {
      cancelado = true;
      window.clearInterval(id);
    };
  }, [revalidator, setup?.actualizacion.estado, setup?.disponible]);

  const cambiarEmail = (indice: number, valor: string) => {
    setEmails((previo) => previo.map((item, i) => (i === indice ? valor : item)));
  };
  const cambiarPassword = (indice: number, valor: string) => {
    setPasswords((previo) => previo.map((item, i) => (i === indice ? valor : item)));
  };
  const alternarVisible = (indice: number) => {
    setVisibles((previo) => previo.map((item, i) => (i === indice ? !item : item)));
  };

  const empezar = async (cuentas?: MegaCuentaIn[]) => {
    setError(null);
    setBusy(true);
    try {
      const siguiente = await api.megaUpdate(cuentas);
      setSetup(siguiente);
      setPasswords(["", "", ""]);
      if (cuentas) {
        setEmails([0, 1, 2].map((i) => cuentas[i]?.email ?? ""));
      }
      if (siguiente.actualizacion.estado !== "en_curso") {
        setBusy(false);
        revalidator.revalidate();
      }
    } catch (fallo) {
      setBusy(false);
      setError(mensajeHumano(fallo));
    }
  };

  const guardarYActualizar = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const cuentas = emails.map((email, indice) => ({
      email: email.trim(),
      password: passwords[indice] ?? "",
    }));
    if (cuentas.some((cuenta) => !cuenta.email || !cuenta.password)) {
      setError("Completa el correo y la contraseña de las tres cuentas.");
      return;
    }
    void empezar(cuentas);
  };

  const actualizarAhora = () => {
    if (!configurado) {
      setError("Guarda primero las tres cuentas.");
      return;
    }
    void empezar();
  };

  const actualizacion = setup?.actualizacion;
  const faseActual = actualizacion?.fase ?? null;
  const indiceFase = PASOS.findIndex((paso) => paso.key === faseActual);
  const terminado = actualizacion?.estado === "ok";
  const fallido = actualizacion?.estado === "error";

  return (
    <>
      <article className="setup-page page-shell" data-testid="mega-setup">
        <Link to="/" className="back-link">
          ← Biblioteca
        </Link>

        <header className="setup-head">
          <p className="page-head__eyebrow">Mantenimiento · cuentas MEGA</p>
          <h1 className="page-head__title">Actualizar biblioteca</h1>
          <p className="setup-lede">
            Introduce las tres cuentas de la rotación. La app comprueba cuál ve la
            biblioteca, descarga el catálogo y aplica los cambios sin tocar las
            fichas IGDB que ya existen.
          </p>
        </header>

        {errorCarga || !setup ? (
          <div className="setup-alert setup-alert--error" role="alert">
            <strong>No se pudo consultar el estado de MEGA.</strong>
            <p>{errorCarga ?? "La API no respondió."}</p>
          </div>
        ) : !setup.disponible ? (
          <div className="setup-alert setup-alert--warn" role="status">
            <strong>Actualización no disponible en este equipo.</strong>
            <p>{setup.motivo ?? "MEGAcmd no está disponible."}</p>
            <p className="setup-alert__note">
              La actualización se ejecuta desde la aplicación de escritorio, donde
              MEGAcmd está instalado. La biblioteca actual sigue navegable.
            </p>
          </div>
        ) : (
          <div className="setup-layout">
            <form className="setup-panel setup-form" noValidate onSubmit={guardarYActualizar}>
              <div className="detail-section-label">
                <span>Cuentas MEGA</span>
                <span>03</span>
              </div>
              <p className="setup-note">
                Se guardan solo en este equipo, con permisos privados. La cuenta
                marcada como preferida se intenta primero; si no ve la biblioteca,
                la app prueba las otras dos automáticamente.
              </p>

              <div className="setup-accounts">
                {[0, 1, 2].map((indice) => {
                  const guardada = setup.cuentas[indice]?.password_guardada;
                  const visible = visibles[indice];
                  return (
                    <div className="setup-account" key={indice}>
                      <span className="setup-account__num" aria-hidden="true">
                        {String(indice + 1).padStart(2, "0")}
                      </span>
                      <div className="setup-account__field">
                        <label htmlFor={`mega-email-${indice}`}>Correo</label>
                        <input
                          id={`mega-email-${indice}`}
                          type="email"
                          name={`email-${indice}`}
                          value={emails[indice] ?? ""}
                          onChange={(event) => cambiarEmail(indice, event.target.value)}
                          autoComplete="off"
                          spellCheck={false}
                          placeholder="cuenta@ejemplo.com"
                          disabled={busy}
                        />
                      </div>
                      <div className="setup-account__field setup-account__password">
                        <label htmlFor={`mega-password-${indice}`}>Contraseña</label>
                        <input
                          id={`mega-password-${indice}`}
                          type={visible ? "text" : "password"}
                          name={`password-${indice}`}
                          value={passwords[indice] ?? ""}
                          onChange={(event) =>
                            cambiarPassword(indice, event.target.value)
                          }
                          autoComplete="off"
                          spellCheck={false}
                          placeholder={
                            guardada
                              ? "Guardada"
                              : "Contraseña MEGA"
                          }
                          disabled={busy}
                        />
                        <button
                          type="button"
                          className="setup-reveal"
                          onClick={() => alternarVisible(indice)}
                          aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
                          aria-pressed={visible}
                        >
                          {visible ? "Ocultar" : "Ver"}
                        </button>
                      </div>
                      {setup.cuentas[indice]?.preferida ? (
                        <span className="setup-account__preferred">Preferida</span>
                      ) : null}
                    </div>
                  );
                })}
              </div>

              {error ? (
                <p className="setup-error" role="alert">
                  {error}
                </p>
              ) : null}

              <div className="setup-actions">
                <button
                  type="submit"
                  className="setup-primary"
                  disabled={busy || !setup.disponible}
                >
                  {busy ? "Actualizando…" : "Guardar y actualizar"}
                </button>
                {configurado ? (
                  <button
                    type="button"
                    className="setup-secondary"
                    onClick={actualizarAhora}
                    disabled={busy || !setup.disponible}
                  >
                    Actualizar ahora
                  </button>
                ) : null}
              </div>
              <p className="setup-note">
                Las contraseñas no se muestran en el catálogo, no se guardan en la
                base de datos y nunca se escriben en los logs.
              </p>
            </form>

            <aside className="setup-panel setup-status" aria-live="polite">
              <div className="detail-section-label">
                <span>Estado</span>
                <span>
                  {actualizacion?.estado === "ok"
                    ? "Actualizado"
                    : actualizacion?.estado === "error"
                      ? "Revisar"
                      : busy
                        ? "En curso"
                        : "Listo"}
                </span>
              </div>

              <div className="setup-status__head">
                {busy ? <span className="setup-spinner" aria-hidden="true" /> : null}
                <p>
                  {actualizacion?.mensaje ??
                    (configurado
                      ? "Cuentas guardadas. Puedes actualizar cuando quieras."
                      : "Aún no hay cuentas guardadas.")}
                </p>
              </div>

              <ol className="setup-progress">
                {PASOS.map((paso, indice) => {
                  const hecho =
                    terminado || (indiceFase >= 0 && indice < indiceFase);
                  const activo = !terminado && indiceFase === indice && !!busy;
                  const roto = fallido && indiceFase === indice;
                  return (
                    <li
                      key={paso.key}
                      className={`${hecho ? "is-done" : ""} ${activo ? "is-active" : ""} ${roto ? "is-error" : ""}`}
                    >
                      <span aria-hidden="true">{hecho ? "✓" : indice + 1}</span>
                      {paso.label}
                    </li>
                  );
                })}
              </ol>

              {terminado && actualizacion ? (
                <div className="setup-result setup-result--ok">
                  <strong>Biblioteca actualizada.</strong>
                  <p>
                    {numero(actualizacion.resumen, "added_files")} archivos nuevos ·{" "}
                    {numero(actualizacion.resumen, "changed_files")} cambiados ·{" "}
                    {numero(actualizacion.resumen, "removed_files")} retirados.
                  </p>
                  {actualizacion.cuenta ? (
                    <p className="setup-result__account">
                      Sesión MEGA: {actualizacion.cuenta}
                    </p>
                  ) : null}
                  <Link to="/" className="setup-result__link">
                    Ver la biblioteca ↗
                  </Link>
                </div>
              ) : null}

              {fallido && actualizacion?.error ? (
                <div className="setup-result setup-result--error" role="alert">
                  <strong>No se aplicó la actualización.</strong>
                  <p>{actualizacion.error}</p>
                  <p className="setup-alert__note">
                    La base de datos y las fichas actuales siguen intactas.
                  </p>
                </div>
              ) : null}

              <dl className="setup-current">
                <div>
                  <dt>Catálogo</dt>
                  <dd>{meta ? `${formatNumber(meta.titles)} juegos` : "Sin datos"}</dd>
                </div>
                <div>
                  <dt>Archivos</dt>
                  <dd>{meta ? formatNumber(meta.files) : "—"}</dd>
                </div>
                <div>
                  <dt>Último volcado</dt>
                  <dd>
                    {sync?.dump_age_hours != null
                      ? `Hace ${edadLegible(sync.dump_age_hours)}`
                      : "—"}
                  </dd>
                </div>
              </dl>
            </aside>
          </div>
        )}
      </article>

      <SiteFooter meta={meta as MetaOut | null} sync={sync as SyncStatusOut | null} />
    </>
  );
}
