import { useEffect, useState } from "react";
import { useLocation } from "react-router";

/**
 * Ancla flotante "↑ TOP". Aparece tras bajar por la página, acompaña al scroll
 * y se retira cuando el drain del footer asoma (su TOP habitual queda justo en
 * el mismo sitio, así que parece que aterriza en su posición).
 */
export function ScrollTopAnchor() {
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);
  const [drainVisible, setDrainVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 520);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    const drain = document.querySelector(".drain");
    let io: IntersectionObserver | null = null;
    if (drain && "IntersectionObserver" in window) {
      io = new IntersectionObserver(
        ([entry]) => setDrainVisible(entry.isIntersecting),
        { threshold: 0.04, rootMargin: "0px 0px -8% 0px" },
      );
      io.observe(drain);
    }

    return () => {
      window.removeEventListener("scroll", onScroll);
      io?.disconnect();
    };
  }, [location.pathname]);

  const visible = scrolled && !drainVisible;
  const target = location.pathname === "/" ? "#biblioteca" : "#top";

  return (
    <a
      href={target}
      className="scroll-top"
      data-visible={visible}
      aria-label="Volver al principio de la lista"
      aria-hidden={!visible}
      tabIndex={visible ? 0 : -1}
    >
      ↑ <span>Top</span>
    </a>
  );
}
