/** Utilidades compartidas de la auditoría. */
import { mkdirSync } from "node:fs";

export const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:7441";
export const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:7440";

/**
 * Totales del volcado canónico vigente (`mega_cuenta_contenido_MEGAcmd.txt`).
 * Una sola fuente de verdad para la auditoría: al refrescar el volcado
 * (`make volcado`) basta actualizar este objeto.
 */
export const VOLCADO = {
  files: 32643,
  folders: 16549,
  titles: 5668,
  bytes: 18472324884151,
  letraA: 688,
};

/** GET a la API (desde Node) con control de error. */
export async function apiGet(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

export function ensureResultsDir(): void {
  mkdirSync(new URL("../results", import.meta.url).pathname, { recursive: true });
}
