import { StrictMode, startTransition } from "react";
import { hydrateRoot } from "react-dom/client";
import { HydratedRouter } from "react-router/dom";

startTransition(() => {
  hydrateRoot(
    document,
    <StrictMode>
      <HydratedRouter />
    </StrictMode>,
    {
      onRecoverableError(error, info) {
        // Diagnóstico de hidratación: identifica el componente que no coincide
        // entre SSR y cliente (no afecta al render normal).
        console.error("[hydrate]", error, info?.componentStack ?? "");
      },
    },
  );
});
