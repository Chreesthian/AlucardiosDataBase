import { reactRouter } from "@react-router/dev/vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Frontend React (React Router 7 en modo framework, SSR) para AlucardiosDataBase.
//
// El diseño es un clon 1:1 de la identidad visual de https://charbeltannous.com/
// (paletas "ink", wordmark a sangre, filas tipográficas, bandas goo, cursor
// propio) adaptado al catálogo de juegos. El CSS es propio y autocontenido.
export default defineConfig({
  plugins: [reactRouter()],
  // Las variables `PUBLIC_*` se hornean en el bundle (igual que en Astro):
  // PUBLIC_BACKEND_HOST/PORT apuntan al servicio interno en Docker.
  envPrefix: ["PUBLIC_"],
  resolve: {
    alias: {
      "~": fileURLToPath(new URL("./app", import.meta.url)),
    },
  },
  server: {
    port: 7330,
    host: true,
  },
});
