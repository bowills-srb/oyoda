import type { ReactNode } from "react";

type SurfaceControlsProps = {
  ariaLabel: string;
  children: ReactNode;
  // When true (focus mode), the header above is hidden, so this panel sticks
  // to the very top instead of below the 72px header.
  flush?: boolean;
};

/**
 * Sticky control panel that sits beneath the surface header.
 * Wraps tab strip + filter bar + metric strip into one cohesive group.
 *
 * top-[72px] matches the rendered height of SurfaceHeader (sticky below it).
 * SurfaceControls owns the bottom border — children (e.g. SurfaceTabs) should
 * not add their own bottom border when nested here.
 */
export function SurfaceControls({ ariaLabel, children, flush = false }: SurfaceControlsProps) {
  return (
    <section
      className={`sticky z-[4] bg-page border-b border-hairline ${flush ? "top-0" : "top-[72px]"}`}
      aria-label={ariaLabel}
    >
      {children}
    </section>
  );
}
