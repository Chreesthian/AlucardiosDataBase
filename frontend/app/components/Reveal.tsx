import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * Envoltorio de aparición al hacer scroll. El observer global vive en
 * `root.tsx` (useRevealOnScroll) y añade `.is-in` cuando entra en viewport.
 */
export function Reveal({
  as: Tag = "div",
  children,
  delay = 0,
  className = "",
}: {
  as?: ElementType;
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <Tag
      className={`reveal ${className}`.trim()}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}
