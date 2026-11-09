import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export interface LightboxImage {
  src: string;
  alt: string;
  caption?: string;
}

/**
 * Visor de imágenes a pantalla completa. Se usa para el banner, la
 * carátula y las capturas de IGDB. Cierra con Escape, clic en el fondo
 * o el botón; las flechas recorren la galería.
 */
export function ImageLightbox({
  images,
  index,
  onClose,
  onIndex,
}: {
  images: LightboxImage[];
  index: number | null;
  onClose: () => void;
  onIndex: (next: number) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const stepRef = useRef<(delta: number) => void>(() => {});

  const step = useCallback(
    (delta: number) => {
      if (index === null || images.length === 0) return;
      const next = (index + delta + images.length) % images.length;
      onIndex(next);
    },
    [images.length, index, onIndex],
  );
  onCloseRef.current = onClose;
  stepRef.current = step;

  const isOpen = index !== null;

  useEffect(() => {
    if (!isOpen) return;
    previousFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        stepRef.current(1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepRef.current(-1);
      }
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus.current?.focus();
    };
  }, [isOpen]);

  if (index === null || images.length === 0) return null;
  if (typeof document === "undefined") return null;

  const image = images[index] ?? images[0];
  if (!image) return null;
  const hasSeveral = images.length > 1;

  return createPortal(
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={image.caption ?? image.alt ?? "Imagen ampliada"}
      data-testid="lightbox"
      onClick={onClose}
    >
      <div
        className="lightbox__frame"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          ref={closeRef}
          type="button"
          className="lightbox__close"
          onClick={onClose}
          aria-label="Cerrar imagen"
        >
          ✕
        </button>

        {hasSeveral ? (
          <button
            type="button"
            className="lightbox__nav lightbox__nav--prev"
            onClick={() => step(-1)}
            aria-label="Imagen anterior"
          >
            ←
          </button>
        ) : null}

        <figure className="lightbox__figure">
          <img
            key={image.src}
            className="lightbox__image"
            src={image.src}
            alt={image.alt}
          />
          <figcaption className="lightbox__caption">
            {image.caption ?? image.alt}
            {hasSeveral ? (
              <span className="lightbox__count">
                {index + 1} / {images.length}
              </span>
            ) : null}
          </figcaption>
        </figure>

        {hasSeveral ? (
          <button
            type="button"
            className="lightbox__nav lightbox__nav--next"
            onClick={() => step(1)}
            aria-label="Imagen siguiente"
          >
            →
          </button>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
