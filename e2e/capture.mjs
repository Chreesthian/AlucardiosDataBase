// Captura de evidencia visual (carátulas IGDB) contra el despliegue.
// node capture.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:7440";
mkdirSync("results", { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });

// Home: espera a que se pinte al menos una carátula de IGDB.
await page.goto(BASE + "/");
await page.waitForSelector('main img[src*="images.igdb.com"]', { timeout: 15000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: "results/home-covers.png" });

// Detalle de un título con portada.
await page.goto(BASE + "/game/1000xresist/");
await page.waitForSelector('main img[src*="images.igdb.com"]', { timeout: 15000 });
await page.waitForTimeout(800);
await page.screenshot({ path: "results/detail-cover.png" });

// Detalle completo (ficha técnica + sinopsis + vídeos + capturas) en scroll total.
await page.goto(BASE + "/game/1000xresist/");
await page.waitForSelector("text=Ficha técnica", { timeout: 15000 });
await page.waitForTimeout(1200);
await page.screenshot({ path: "results/detail-ficha-full.png", fullPage: true });

await browser.close();
console.log("capturas OK → e2e/results/");
