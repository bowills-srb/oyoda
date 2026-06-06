import type { ReactNode, RefObject } from "react";

type AnchoredPanelProps = {
  anchorClassName: string;
  anchorRef: RefObject<HTMLDivElement>;
  open: boolean;
  panel: ReactNode;
  panelAriaLabel: string;
  panelClassName: string;
  panelRole: "dialog" | "menu";
  trigger: ReactNode;
};

/**
 * Shared anchor + trigger + conditional panel shell.
 *
 * This intentionally does not impose any visual styling. Callers keep their
 * existing class names so ongoing UI work stays flexible while the structure
 * becomes consistent.
 */
export function AnchoredPanel({
  anchorClassName,
  anchorRef,
  open,
  panel,
  panelAriaLabel,
  panelClassName,
  panelRole,
  trigger,
}: AnchoredPanelProps) {
  return (
    <div className={anchorClassName} ref={anchorRef}>
      {trigger}
      {open ? (
        <div className={panelClassName} role={panelRole} aria-label={panelAriaLabel}>
          {panel}
        </div>
      ) : null}
    </div>
  );
}
