import { useCustomCursor } from "~/lib/hooks";

/** Punto + etiqueta que siguen al puntero (solo en dispositivos de puntero fino). */
export function Cursor() {
  const { dotRef, labelRef } = useCustomCursor(true);
  return (
    <>
      <div ref={dotRef} className="cursor" aria-hidden="true" />
      <div ref={labelRef} className="cursor-label" aria-hidden="true" />
    </>
  );
}
