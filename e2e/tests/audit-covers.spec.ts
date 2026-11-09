/**
 * Auditoría de carátulas IGDB: que la API publique URLs reales, que las
 * imágenes se sirvan y que se pinten POR ENCIMA del fallback de iniciales
 * (el bug que ocultaba las carátulas en la primera versión del rediseño).
 */
import { expect, test } from "@playwright/test";

import { apiGet } from "./helpers";

test.describe("IGDB · carátulas", () => {
  test("la API publica URLs válidas y las imágenes responden", async () => {
    const { status, body } = await apiGet("/api/titles?limit=24");
    expect(status).toBe(200);
    const covers = body.items
      .map((item: any) => item.igdb_cover)
      .filter((url: unknown): url is string => typeof url === "string" && url.length > 0);
    expect(covers.length).toBeGreaterThan(0);

    for (const url of covers.slice(0, 6)) {
      expect(url.startsWith("https://images.igdb.com/")).toBeTruthy();
      const res = await fetch(url, { method: "HEAD" });
      expect(res.ok, `${url} debe responder 2xx`).toBeTruthy();
      expect(res.headers.get("content-type") ?? "").toContain("image/");
    }
  });

  test("la ficha pinta la carátula por encima del fallback", async ({ page }) => {
    const { body } = await apiGet("/api/titles?limit=1");
    const slug = body.items[0].slug;
    await page.goto(`/game/${slug}/`);

    const img = page.locator(".detail-cover img");
    await expect(img).toHaveCount(1);
    await expect(img).toBeVisible();
    await expect
      .poll(
        async () => img.evaluate((el) => (el as HTMLImageElement).naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);

    // La ficha nueva es más editorial: la carátula vive bajo el banner, así
    // que hay que traerla al viewport antes de comprobar el z-index.
    const coverEl = page.locator(".detail-cover");
    await coverEl.scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);

    const topTag = await page.evaluate(() => {
      const cover = document.querySelector(".detail-cover");
      if (!cover) return null;
      const rect = cover.getBoundingClientRect();
      const el = document.elementFromPoint(
        rect.left + rect.width / 2,
        rect.top + rect.height / 2,
      );
      return el?.tagName ?? null;
    });
    expect(topTag).toBe("IMG");
  });

  test("la rejilla carga carátulas y las pinta encima del fallback", async ({ page }) => {
    await page.goto("/?vista=cuadricula");
    const card = page.locator(".cover-card").first();
    await card.scrollIntoViewIfNeeded();

    const img = card.locator(".cover-card__art img");
    await expect(img).toHaveCount(1);
    await expect
      .poll(
        async () => img.evaluate((el) => (el as HTMLImageElement).naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);

    const topTag = await page.evaluate(() => {
      const art = document.querySelector(".cover-card__art");
      if (!art) return null;
      const rect = art.getBoundingClientRect();
      const el = document.elementFromPoint(
        rect.left + rect.width / 2,
        rect.top + rect.height / 2,
      );
      return el?.tagName ?? null;
    });
    expect(topTag).toBe("IMG");
  });

  test("el panel de la biblioteca pide la carátula 2x y la pinta encima", async ({ page }) => {
    await page.goto("/");
    const panel = page.locator(".work-panel__cover").first();
    await panel.scrollIntoViewIfNeeded();

    const img = page.locator(".work-panel__cover img").first();
    await expect(img).toBeVisible();
    await expect
      .poll(
        async () => img.evaluate((el) => (el as HTMLImageElement).naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);
    expect(await img.getAttribute("src")).toContain("t_cover_big_2x");

    const topTag = await page.evaluate(() => {
      const cover = document.querySelector(".work-panel__cover");
      if (!cover) return null;
      const rect = cover.getBoundingClientRect();
      const el = document.elementFromPoint(
        rect.left + rect.width / 2,
        rect.top + rect.height / 2,
      );
      return el?.tagName ?? null;
    });
    expect(topTag).toBe("IMG");
  });
});
