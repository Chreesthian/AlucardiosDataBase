import type { Config } from "@react-router/dev/config";

// SSR activo: la portada, las fichas y las secciones se renderizan en el
// servidor (SEO + primer pintado + códigos 404 reales, igual que el SSR de
// Astro que sustituye este frontend).
export default {
  ssr: true,
} satisfies Config;
