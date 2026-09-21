/**
 * Auditoría EXTERNA: navegador real (Chromium) contra el despliegue publicado.
 * Cubre SSR, navegación, buscador autosuggest, chips de letra, orden y detalle.
 */
import { expect, test, type Page } from "@playwright/test";
import { apiGet, ensureResultsDir, VOLCADO } from "./helpers";

/** Colecciona errores de consola/página para fallar si aparecen. */
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // Aviso interno de Chromium (no de la app) al cargar iframes de vídeo.
    if (m.type() === "error" && !m.text().includes("compute-pressure is not allowed")) {
      errors.push(m.text());
    }
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

const CARDS = 'main a[href^="/game/"][title]';

test("home: SSR renderiza la biblioteca con métricas reales", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Biblioteca" })).toBeVisible();

  // Métricas del snapshot (vía SSR) presentes en la cabecera.
  await expect(page.getByText("juegos").first()).toBeVisible();
  await expect(page.getByText("archivos").first()).toBeVisible();

  // Grid con las 60 tarjetas de la primera página.
  const cards = page.locator(CARDS);
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBe(60);

  // La URL pública de la API queda disponible para el JS del navegador.
  const apiBase = await page.evaluate(() => (window as any).__ALUCARD_API);
  expect(apiBase).toContain(`${new URL(page.url()).hostname}`);

  ensureResultsDir();
  await page.screenshot({ path: "results/home.png", fullPage: false });
  expect(errors).toEqual([]);
});

test("buscador autosuggest resuelve y navega al detalle", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.locator("#search-input").fill("zelda echo");

  const box = page.locator("#search-results");
  await expect(box).toBeVisible();
  const opt = box.locator("a", { hasText: "Zelda Echoes of Wisdom" });
  await expect(opt.first()).toBeVisible();

  await opt.first().click();
  await page.waitForURL(/\/game\/the-legend-of-zelda-echoes-of-wisdom\//);
  await expect(
    page.getByRole("heading", { level: 1 }),
  ).toContainText("The Legend of Zelda Echoes of Wisdom");
  expect(errors).toEqual([]);
});

test("filtro por letra vía chips (URL ?letter=A)", async ({ page }) => {
  const meta = (await apiGet("/api/meta")).body;
  const bucketA = meta.buckets.find((b: any) => b.letter === "A");
  await page.goto("/");
  await page
    .locator(`nav[aria-label="Letras"] a[title="${bucketA.titles} juegos"]`)
    .click();
  await page.waitForURL(/letter=A/);
  await expect(page.getByText(`${bucketA.titles} resultados`)).toBeVisible();
});

test("orden por tamaño: el mayor juego primero", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Tamaño" }).click();
  await page.waitForURL(/sort=size/);
  const first = page.locator(CARDS).first();
  await expect(first).toContainText("INAZUMA ELEVEN Victory Road");
  ensureResultsDir();
  await page.screenshot({ path: "results/sort-size.png" });
});

test("paginación SSR: siguiente/anterior mantienen offset coherente", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Siguiente/ }).click();
  await page.waitForURL(/offset=60/);
  await expect(page.getByText(`${VOLCADO.titles} resultados`)).toBeVisible();
  const secondPageFirst = (await page.locator(CARDS).first().innerText()).trim();
  expect(secondPageFirst.length).toBeGreaterThan(0);

  await page.getByRole("link", { name: /Anterior/ }).click();
  await page.waitForURL((u) => !u.searchParams.has("offset"));
  expect(await page.locator(CARDS).count()).toBe(60);
});

test("detalle de un juego con versiones y archivos", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/game/the-legend-of-zelda-echoes-of-wisdom/");
  await expect(
    page.getByRole("heading", { level: 1 }),
  ).toContainText("The Legend of Zelda Echoes of Wisdom");

  await expect(page.getByRole("heading", { name: "Versiones" })).toBeVisible();
  await expect(page.getByText("VERSIÓN BASE", { exact: true })).toBeVisible();

  // Algún archivo real (Zelda está empaquetado en .rar) listado con tamaño.
  const fileRow = page.locator("li", { hasText: /\.rar/ }).first();
  await expect(fileRow).toBeVisible();

  ensureResultsDir();
  await page.screenshot({ path: "results/detail-zelda.png" });
  expect(errors).toEqual([]);
});

test("navegación directa a detalle inexistente muestra estado controlado", async ({ page }) => {
  const response = await page.goto("/game/slug-que-no-existe/");
  expect(response?.status()).toBe(404);
  await expect(page.getByText("No se pudo cargar el juego")).toBeVisible();
});
