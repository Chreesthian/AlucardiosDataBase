import { useEffect, useRef } from "react";

/**
 * Logotipo del hero. Se sirve el SVG vectorial (sin PNG ni fuentes) y se
 * inclina/desplaza unos píxeles siguiendo el puntero, con una interpolación
 * larga para que el movimiento sea sedoso. En táctil y reduced-motion no se
 * instala el listener.
 */
export function HeroLogo() {
  const logoRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const logo = logoRef.current;
    if (!logo) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    let last = 0;
    let targetX = 0;
    let targetY = 0;
    let targetRotX = 0;
    let targetRotY = 0;
    let currentX = 0;
    let currentY = 0;
    let currentRotX = 0;
    let currentRotY = 0;

    const clamp = (value: number, min: number, max: number) =>
      Math.min(max, Math.max(min, value));

    const paint = (now: number) => {
      const dt = last ? Math.min(64, now - last) : 16.67;
      last = now;
      // Muy poca velocidad: el logo termina de asentarse en ~1 s.
      const ease = 1 - Math.exp(-dt / 180);

      currentX += (targetX - currentX) * ease;
      currentY += (targetY - currentY) * ease;
      currentRotX += (targetRotX - currentRotX) * ease;
      currentRotY += (targetRotY - currentRotY) * ease;

      logo.style.setProperty("--logo-x", `${currentX.toFixed(2)}px`);
      logo.style.setProperty("--logo-y", `${currentY.toFixed(2)}px`);
      logo.style.setProperty("--logo-rx", `${currentRotX.toFixed(3)}deg`);
      logo.style.setProperty("--logo-ry", `${currentRotY.toFixed(3)}deg`);

      const settled =
        Math.abs(targetX - currentX) < 0.01 &&
        Math.abs(targetY - currentY) < 0.01 &&
        Math.abs(targetRotX - currentRotX) < 0.001 &&
        Math.abs(targetRotY - currentRotY) < 0.001;

      if (settled) {
        logo.style.setProperty("--logo-x", "0px");
        logo.style.setProperty("--logo-y", "0px");
        logo.style.setProperty("--logo-rx", "0deg");
        logo.style.setProperty("--logo-ry", "0deg");
        frame = 0;
        last = 0;
        return;
      }

      frame = requestAnimationFrame(paint);
    };

    const kick = () => {
      if (!frame) {
        last = 0;
        frame = requestAnimationFrame(paint);
      }
    };

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const x = clamp(event.clientX / window.innerWidth - 0.5, -0.5, 0.5);
      const y = clamp(event.clientY / window.innerHeight - 0.5, -0.5, 0.5);

      // 18 px / 2.2° como máximo: presencia, nunca protagonismo.
      targetX = x * 18;
      targetY = y * 12;
      targetRotY = x * 2.2;
      targetRotX = -y * 1.4;
      kick();
    };

    const reset = () => {
      targetX = 0;
      targetY = 0;
      targetRotX = 0;
      targetRotY = 0;
      kick();
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", reset);
    window.addEventListener("blur", reset);

    return () => {
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", reset);
      window.removeEventListener("blur", reset);
      if (frame) cancelAnimationFrame(frame);
      logo.style.removeProperty("--logo-x");
      logo.style.removeProperty("--logo-y");
      logo.style.removeProperty("--logo-rx");
      logo.style.removeProperty("--logo-ry");
    };
  }, []);

  return <span ref={logoRef} className="hero-logo" aria-hidden="true" />;
}
