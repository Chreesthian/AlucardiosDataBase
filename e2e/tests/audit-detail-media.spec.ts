/**
 * Auditoría de la ficha de juego: banner y sinopsis servidos por IGDB,
 * título "tape" y visor de imágenes. Complementa audit-ui/audit-covers.
 */
import { expect, test } from "@playwright/test";

const ZELDA = "/game/the-legend-of-zelda-echoes-of-wisdom/";

test.describe("detalle · media y transiciones", () => {
  test("banner, sinopsis y título tape desde IGDB", async ({ page }) => {
    await page.goto(ZELDA);
    await expect(page.getByTestId("detail-banner")).toBeVisible();

    const banner = page.locator(".detail-banner__img");
    await expect(banner).toBeVisible();
    await expect
      .poll(
        async () => banner.evaluate((el) => (el as HTMLImageElement).naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);

    await expect(page.getByTestId("detail-synopsis")).toContainText(
      /Hyrule|Zelda/i,
    );
    expect(await page.locator(".tape-letter").count()).toBeGreaterThan(10);

    const transitionName = await page
      .locator("h1.detail-title")
      .evaluate((el) => (el as HTMLElement).style.viewTransitionName);
    expect(transitionName).toBe("game-title");
  });

  test("banner, carátula y capturas se amplían en el lightbox", async ({
    page,
  }) => {
    await page.goto(ZELDA);
    const lightbox = page.getByTestId("lightbox");

    // Captura -> visor -> Escape.
    await page.locator(".detail-shot").first().click();
    await expect(lightbox).toBeVisible();
    await expect
      .poll(
        async () =>
          lightbox
            .locator("img")
            .evaluate((el) => (el as HTMLImageElement).naturalWidth),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);
    await page.keyboard.press("Escape");
    await expect(lightbox).toHaveCount(0);

    // Banner -> visor -> botón de cierre.
    await page.locator(".detail-banner__open").click();
    await expect(lightbox).toBeVisible();
    await page.getByRole("button", { name: "Cerrar imagen" }).click();
    await expect(lightbox).toHaveCount(0);

    // Carátula -> visor -> Escape.
    await page.locator(".detail-cover").click();
    await expect(lightbox).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(lightbox).toHaveCount(0);
  });

  test("lista → ficha comparte el título con View Transition", async ({
    page,
  }) => {
    await page.goto("/");
    const supportsViewTransitions = await page.evaluate(
      () => typeof document.startViewTransition === "function",
    );
    test.skip(!supportsViewTransitions, "El navegador no soporta View Transitions");

    await page.evaluate(() => {
      const original = document.startViewTransition.bind(document);
      (window as any).__vt = 0;
      document.startViewTransition = ((callback: any) => {
        (window as any).__vt += 1;
        return original(callback);
      }) as typeof document.startViewTransition;
    });

    const row = page.locator(".work-row").first();
    await row.hover();
    await expect(row.locator('[data-motion="name"]')).toHaveAttribute(
      "style",
      /view-transition-name:\s*game-title/,
    );
    await row.click();
    await page.waitForURL(/\/game\/.+\//);
    await expect
      .poll(() => page.evaluate(() => (window as any).__vt), {
        timeout: 10_000,
      })
      .toBeGreaterThan(0);
    await expect(page.locator("h1.detail-title")).toBeVisible();
  });
});
