/** Comprobación real (Playwright): clics de descarga carpeta y archivo en 1-2 Switch. */
import { test } from "@playwright/test";

test("1-2 Switch · descarga real carpeta y archivo", async ({ page }) => {
  await page.goto(`/game/1-2-switch/`);
  await page.waitForSelector('a[data-download]');
  const nav: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/download"))
      nav.push(`API ${r.status()} loc=${r.headers().location} remote=${r.headers()["x-download-remote"]}`);
  });
  page.on("framenavigated", (f) => nav.push(`NAV ${f.url()}`));

  // Carpeta (BASE): click real en el <a> (dentro del summary del detalle).
  await page.evaluate(() => {
    const a = Array.from(document.querySelectorAll("a[data-download]")).find((x) =>
      (x.textContent || "").includes("carpeta"));
    if (a) (a as HTMLAnchorElement).click();
  });
  await page.waitForTimeout(3500);
  console.log("FOLDER >>", nav.slice(-4).join(" | "));
  console.log("URL    >>", page.url());

  await page.goto(`/game/1-2-switch/`);
  await page.waitForSelector('a[data-download]');
  nav.length = 0;
  // Archivo (primer ⬇ sin la etiqueta carpeta).
  await page.evaluate(() => {
    const a = Array.from(document.querySelectorAll("a[data-download]")).find((x) =>
      !(x.textContent || "").includes("carpeta"));
    if (a) (a as HTMLAnchorElement).click();
  });
  await page.waitForTimeout(3500);
  console.log("FILE  >>", nav.slice(-4).join(" | "));
  console.log("URL   >>", page.url());
});
