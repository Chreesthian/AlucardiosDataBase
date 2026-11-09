import { useCallback, useEffect, useRef, useState } from "react";

export type Ink = "dusk" | "night" | "day" | "morning";

export const INKS: Array<{ id: Ink; label: string }> = [
  { id: "dusk", label: "Dusk" },
  { id: "night", label: "Night" },
  { id: "day", label: "Day" },
  { id: "morning", label: "Morning" },
];

const INK_KEY = "alucard:ink";

/** Lee la tinta guardada (o la de SSR) sin tocar el DOM. */
export function readInk(): Ink {
  if (typeof document === "undefined") return "dusk";
  const stored = localStorage.getItem(INK_KEY) as Ink | null;
  if (stored && INKS.some((i) => i.id === stored)) return stored;
  const attr = document.documentElement.dataset.ink as Ink | undefined;
  return attr && INKS.some((i) => i.id === attr) ? attr : "dusk";
}

/** Cambia la tinta de la casa: actualiza <html data-ink> y persiste. */
export function useInk() {
  const [ink, setInk] = useState<Ink>("dusk");

  useEffect(() => {
    setInk(readInk());
  }, []);

  const apply = useCallback((next: Ink) => {
    setInk(next);
    document.documentElement.dataset.ink = next;
    try {
      localStorage.setItem(INK_KEY, next);
    } catch {
      /* almacenamiento no disponible */
    }
  }, []);

  const cycle = useCallback(() => {
    const current = readInk();
    const idx = INKS.findIndex((i) => i.id === current);
    apply(INKS[(idx + 1) % INKS.length].id);
  }, [apply]);

  return { ink, apply, cycle };
}

/**
 * Revela al hacer scroll los nodos `.reveal` de la página actual. Se vuelve a
 * enganchar en cada navegación porque React Router sustituye el árbol.
 */
export function useRevealOnScroll(key: string) {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(".reveal:not(.is-in)"));
    if (!nodes.length) return;

    if (!("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("is-in"));
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 },
    );

    nodes.forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [key]);
}

/** Cursor propio: punto + etiqueta sobre elementos `[data-cursor]`. */
export function useCustomCursor(enabled: boolean) {
  const dotRef = useRef<HTMLDivElement | null>(null);
  const labelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const fine = window.matchMedia("(pointer: fine)").matches;
    if (!fine) return;

    let raf = 0;
    let x = -100;
    let y = -100;

    const paint = () => {
      raf = 0;
      const dot = dotRef.current;
      const label = labelRef.current;
      if (dot) dot.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      if (label) label.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };

    const onMove = (e: PointerEvent) => {
      x = e.clientX;
      y = e.clientY;
      document.body.dataset.cursorActive = "true";
      if (!raf) raf = requestAnimationFrame(paint);

      const target = (e.target as Element | null)?.closest<HTMLElement>("[data-cursor]");
      const label = labelRef.current;
      if (label) {
        const text = target?.dataset.cursorLabel ?? "";
        label.textContent = text;
        label.dataset.visible = target && text ? "true" : "false";
      }
    };

    const onLeave = () => {
      document.body.dataset.cursorActive = "false";
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);

    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled]);

  return { dotRef, labelRef };
}
