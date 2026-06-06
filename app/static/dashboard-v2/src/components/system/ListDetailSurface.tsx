import * as Dialog from "@radix-ui/react-dialog";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { cn } from "../../lib/utils";

type ListDetailSurfaceProps = {
  list: ReactNode;

  // Detail content for the current selection. Absent => nothing selected.
  detail?: ReactNode;

  // Whether a selection is active. Drives layout + a11y directly — the
  // primitive reads this prop to apply conditional Tailwind utilities.
  detailOpen: boolean;

  // Caller-owned close handler (clears selection).
  onCloseDetail: () => void;

  // a11y label for the detail region.
  detailAriaLabel: string;

  // Optional augmentation merged via cn() on top of the baked-in structure.
  // Structural layout (flex/grid, overflow, breakpoint split) is the
  // primitive's responsibility. These are for surface-specific overrides.
  className?: string;
  listClassName?: string;
  detailClassName?: string;

  // Ref forwarded to the detail region for caller focus management on open.
  detailRef?: RefObject<HTMLDivElement>;
};

type LegacyMediaQueryList = MediaQueryList & {
  addListener?: (listener: (event: MediaQueryListEvent) => void) => void;
  removeListener?: (listener: (event: MediaQueryListEvent) => void) => void;
};

function subscribeToMediaQuery(
  media: LegacyMediaQueryList,
  listener: (event: MediaQueryListEvent) => void,
) {
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }
  if (typeof media.addListener === "function") {
    media.addListener(listener);
    return () => media.removeListener?.(listener);
  }
  return () => {};
}

/**
 * Shared list + detail layout primitive.
 *
 * Desktop ≥1024px:
 *   Plain flex split. List column narrows to 340px; detail fills the rest.
 *   role="complementary". Phase 5.2: slide+fade in/out via usePresence hook
 *   (Option A fallback — non-modal Dialog fought the flex layout; presence hook
 *   is a small, contained pattern that doesn't re-architect the component).
 *
 * Below 1024px:
 *   Radix Dialog handles the mobile sheet (focus trap, Escape, aria-modal,
 *   Dialog.Overlay for backdrop). Phase 5.2: CSS animations (enter) + data-state
 *   transitions (exit) using Radix's built-in presence.
 *
 * prefers-reduced-motion: all transitions/animations are gated via
 *   motion-reduce:transition-none / motion-reduce:animate-none. Reduced-motion
 *   users get instant show/hide.
 */

// ── Presence hook (desktop detail pane) ──────────────────────────────────────
// Keeps the pane rendered while animating out; unmounts on transitionend so the
// timing stays driven by CSS, never by a hardcoded timeout.
//
// Returns { rendered, visible, ref }:
//   rendered — whether to render the DOM node (true while enter+visible+exit)
//   visible  — whether to apply "visible" CSS classes; false triggers exit transition
//   ref      — attach to the detail div so transitionend can trigger unmount

function usePresence(open: boolean): {
  rendered: boolean;
  visible: boolean;
  ref: React.RefObject<HTMLDivElement>;
} {
  const prefersReducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const [rendered, setRendered] = useState(open);
  const [visible, setVisible] = useState(open);
  const divRef = useRef<HTMLDivElement>(null);
  // Keep a stable ref to the latest open value for the transitionend listener
  const openRef = useRef(open);
  useEffect(() => {
    openRef.current = open;
  });

  useEffect(() => {
    if (open) {
      setRendered(true);
      if (prefersReducedMotion) {
        // Instant show — no transition, no rAF needed
        setVisible(true);
        return;
      }
      // Let the "enter-start" state paint before transitioning in.
      // rAF fires after React commits + browser paints — safe to flip visible.
      const frame = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(frame);
    } else {
      setVisible(false);
      if (prefersReducedMotion) {
        setRendered(false);
        return;
      }
      const node = divRef.current;
      if (!node) {
        setRendered(false);
        return;
      }
      const onTransitionEnd = (e: TransitionEvent) => {
        // Only react to transitions on this node, not bubbled children
        if (e.target === node && !openRef.current) {
          setRendered(false);
        }
      };
      node.addEventListener("transitionend", onTransitionEnd);
      return () => node.removeEventListener("transitionend", onTransitionEnd);
    }
    // prefersReducedMotion is stable (window.matchMedia result at mount)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return { rendered, visible, ref: divRef };
}

function useIsMobileLayout(): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(
    () =>
      typeof window !== "undefined"
        ? window.matchMedia("(max-width: 1023px)").matches
        : false,
  );

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    return subscribeToMediaQuery(mq, handler);
  }, []);

  return isMobile;
}

export function ListDetailSurface({
  list,
  detail,
  detailOpen,
  onCloseDetail,
  detailAriaLabel,
  className,
  listClassName,
  detailClassName,
  detailRef,
}: ListDetailSurfaceProps) {
  const isMobile = useIsMobileLayout();
  const { rendered, visible, ref: presenceRef } = usePresence(detailOpen && !isMobile);

  // Merge the caller's detailRef with our presenceRef (both need the same node)
  const mergedRef = useCallback(
    (node: HTMLDivElement | null) => {
      (presenceRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
      if (detailRef) {
        (detailRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
      }
    },
    // presenceRef is stable (useRef); detailRef is caller-owned
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detailRef],
  );

  return (
    <div className={cn("flex h-full min-h-0 items-stretch", className)}>
      {/* List column — full width when closed; narrows on desktop when open */}
      <div
        className={cn(
          "overflow-y-auto",
          detailOpen && !isMobile
            ? "w-[340px] flex-none border-r border-hairline"
            : "flex-1",
          // On mobile, hide the list behind the Dialog overlay when open
          detailOpen && isMobile ? "hidden" : "",
          listClassName,
        )}
      >
        {list}
      </div>

      {/* Desktop detail — presence-managed so exit can animate.
          Option A decision: non-modal Radix Dialog would fight the flex layout
          (Dialog.Portal renders into document.body by default; keeping it inline
          requires a custom container prop + extra layout work that's not worth it
          for a side-by-side pane). The presence hook is the documented fallback:
          keeps the pane rendered through exit, unmounts on transitionend. */}
      {rendered && !isMobile ? (
        <div
          ref={mergedRef}
          className={cn(
            "min-w-0 flex-1 overflow-y-auto outline-none",
            // Phase 5.2 slide+fade — enter-start: invisible offset; visible: settled
            "transition-[opacity,transform] duration-[180ms]",
            visible ? "ease-out opacity-100 translate-x-0" : "ease-in opacity-0 translate-x-3",
            "motion-reduce:transition-none motion-reduce:opacity-100 motion-reduce:translate-x-0",
            detailClassName,
          )}
          role="complementary"
          aria-label={detailAriaLabel}
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              onCloseDetail();
            }
          }}
        >
          {detail}
        </div>
      ) : null}

      {/* Mobile detail — Radix Dialog handles focus trap, Escape, aria-modal.
          Phase 5.2: CSS @keyframes for enter (data-[state=open]); CSS transition
          for exit (data-[state=closed]) — Radix keeps content mounted through
          close animation via its built-in presence mechanism. */}
      {isMobile ? (
        <Dialog.Root
          open={detailOpen}
          onOpenChange={(open) => {
            if (!open) onCloseDetail();
          }}
        >
          <Dialog.Portal>
            <Dialog.Overlay
              className={cn(
                "fixed inset-0 z-[199] bg-black/20",
                // Enter: keyframe fade-in; Exit: transition to transparent
                "data-[state=open]:animate-overlay-in",
                "data-[state=closed]:opacity-0 transition-opacity duration-[160ms] ease-in",
                "motion-reduce:animate-none motion-reduce:transition-none motion-reduce:opacity-100",
              )}
            />
            <Dialog.Content
              ref={detailRef}
              className={cn(
                "fixed inset-0 z-[200] overflow-y-auto bg-page outline-none",
                // Enter: keyframe slide-up; Exit: transition to offset/transparent
                "data-[state=open]:animate-sheet-in",
                "data-[state=closed]:opacity-0 data-[state=closed]:translate-y-4",
                "transition-[opacity,transform] duration-[180ms] ease-in",
                "motion-reduce:animate-none motion-reduce:transition-none motion-reduce:opacity-100 motion-reduce:translate-y-0",
                detailClassName,
              )}
              aria-label={detailAriaLabel}
              // Radix Dialog already handles Escape → onOpenChange(false)
            >
              {detail}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      ) : null}
    </div>
  );
}
