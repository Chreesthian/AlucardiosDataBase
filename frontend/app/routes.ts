import { type RouteConfig, index, route } from "@react-router/dev/routes";

/**
 * Rutas del catálogo. Se conservan las URLs del frontend anterior para no
 * romper enlaces, la PWA ni la auditoría e2e (incluida la barra final).
 */
export default [
  index("routes/home.tsx"),
  route("game/:slug", "routes/game.tsx"),
  route("novedades", "routes/novedades.tsx"),
  route("retro", "routes/retro.tsx"),
  route("retro/game/:slug", "routes/retro-game.tsx"),
  route("actualizar", "routes/update.tsx"),
  route("*", "routes/not-found.tsx"),
] satisfies RouteConfig;
