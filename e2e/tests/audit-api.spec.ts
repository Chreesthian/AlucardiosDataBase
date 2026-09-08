/**
 * Auditoría INTERNA: la API REST y la coherencia de la base de datos ingerida.
 * Valores esperados = snapshot real del volcado MEGA (30.771 archivos / 5.374 títulos).
 */
import { expect, test } from "@playwright/test";
import { apiGet } from "./helpers";

test.describe("API · salud y despliegue", () => {
  test("GET /api/health responde ok y con snapshots", async () => {
    const { status, body } = await apiGet("/api/health");
    expect(status).toBe(200);
    expect(body.status).toBe("ok");
    expect(body.database).toBe("ok");
    expect(body.version).toBeTruthy();
    expect(body.snapshots).toBeGreaterThanOrEqual(1);
  });

  test("GET /api/sync/status refleja el despliegue real", async () => {
    const { status, body } = await apiGet("/api/sync/status");
    expect(status).toBe(200);
    expect(body.last_snapshot).not.toBeNull();
    expect(body.dump_exists).toBe(true);
    expect(typeof body.megacmd_available).toBe("boolean");
  });
});

test.describe("API · coherencia de la ingesta", () => {
  test("GET /api/meta coincide con el volcado real", async () => {
    const { status, body } = await apiGet("/api/meta");
    expect(status).toBe(200);
    const snap = body.snapshot;
    expect(snap).not.toBeNull();
    expect(snap.source_kind).toBe("dump");
    expect(snap.account).toContain("@");
    expect(body.files).toBe(30771);
    expect(body.folders).toBe(15629);
    expect(body.titles).toBe(5374);
    expect(body.bytes).toBe(17555391856377);
    expect(body.buckets.length).toBe(27);

    // Coherencia interna: la suma de títulos por bucket == total.
    const suma = body.buckets.reduce((a: number, b: any) => a + b.titles, 0);
    expect(suma).toBe(body.titles);
    expect(body.buckets[0].letter).toBe("#");
  });

  test("GET /api/buckets devuelve las 27 letras ordenadas", async () => {
    const { status, body } = await apiGet("/api/buckets");
    expect(status).toBe(200);
    const letters = body.map((b: any) => b.letter);
    expect(letters).toContain("#");
    expect(letters).toContain("Z");
    expect(new Set(letters).size).toBe(27);
  });

  test("pagina listado de títulos (60 por defecto)", async () => {
    const { body } = await apiGet("/api/titles?limit=60");
    expect(body.total).toBe(5374);
    expect(body.items.length).toBe(60);
    expect(body.limit).toBe(60);
    const first = body.items[0];
    expect(first.slug).toBeTruthy();
    expect(typeof first.size_bytes).toBe("number");
  });

  test("filtro por letra A → 655 títulos", async () => {
    const { body } = await apiGet("/api/titles?letter=A&limit=1");
    expect(body.total).toBe(655);
    expect(body.items[0].letter).toBe("A");
  });

  test("búsqueda 'zelda' → 7 resultados con Echoes of Wisdom", async () => {
    const { body } = await apiGet("/api/titles?q=zelda&limit=20");
    expect(body.total).toBe(7);
    const nombres = body.items.map((i: any) => i.name);
    expect(nombres).toContain("The Legend of Zelda Echoes of Wisdom");
  });

  test("orden por tamaño: primero INAZUMA ELEVEN Victory Road", async () => {
    const { body } = await apiGet("/api/titles?sort=size&limit=1");
    expect(body.items[0].slug).toBe("inazuma-eleven-victory-road");
    expect(body.items[0].size_bytes).toBe(185601093061);
  });
});

test.describe("API · detalle de título", () => {
  test("detalle de Zelda con versiones y archivos RAR", async () => {
    const { status, body } = await apiGet(
      "/api/titles/the-legend-of-zelda-echoes-of-wisdom",
    );
    expect(status).toBe(200);
    expect(body.name).toBe("The Legend of Zelda Echoes of Wisdom");
    expect(body.formats).toContain("RAR");
    expect(body.versions.length).toBeGreaterThan(0);
    const labels = body.versions.map((v: any) => v.label);
    expect(labels).toContain("base");
    // al menos un archivo real en el árbol
    const conArchivo = body.versions.find((v: any) => v.files.length > 0);
    expect(conArchivo).toBeTruthy();
  });

  test("existe al menos un título NSP y su detalle lo refleja", async () => {
    // Escanea el listado (ext_json) hasta dar con un título con formato NSP.
    const step = 500;
    let slug: string | null = null;
    for (let offset = 0; offset < 5374 && !slug; offset += step) {
      const { body } = await apiGet(`/api/titles?limit=${step}&offset=${offset}`);
      for (const item of body.items) {
        const exts = JSON.parse(item.ext_json || "{}") as Record<string, number>;
        if (exts.nsp || exts.nsz) {
          slug = item.slug;
          break;
        }
      }
    }
    expect(slug).not.toBeNull();
    const { status, body } = await apiGet(`/api/titles/${slug}`);
    expect(status).toBe(200);
    expect(body.formats).toContain("NSP");
  });

  test("detalle devuelve 404 con mensaje para slugs inexistentes", async () => {
    const { status, body } = await apiGet("/api/titles/no-existe-este-juego");
    expect(status).toBe(404);
    expect(body.detail).toBeTruthy();
  });
});
