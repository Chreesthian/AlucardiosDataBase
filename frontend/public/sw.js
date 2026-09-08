/* Alucard — Service Worker (PWA instalable).
 * Estrategia segura para un SSR + API:
 *  - Navegaciones y /api/* → siempre a red (contenido fresco).
 *  - Estáticos hasheados (/icons, /favicon, /_astro/*) → caché primero.
 * Al desplegar una versión nueva se cambia el nombre de caché (bump abajo).
 */
const CACHE = "alucard-v2";
const PRECACHE = [
  "/manifest.webmanifest",
  "/favicon.svg",
  "/brand/logo.png",
  "/brand/emblem.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // nunca cachear CDNs/API remotas

  // API y navegaciones → siempre red (SSR fresco).
  if (url.pathname.startsWith("/api/") || req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (req.mode === "navigate" && res.ok) {
            const clon = res.clone();
            caches.open(CACHE).then((c) => c.put("/", clon));
          }
          return res;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE);
          const fallback = await cache.match(url.pathname === "/" ? "/" : req);
          return fallback || Response.error();
        })
    );
    return;
  }

  // Estáticos → caché primero, red de relleno.
  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          const clon = res.clone();
          caches.open(CACHE).then((c) => c.put(req, clon));
          return res;
        })
    )
  );
});
