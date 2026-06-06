import { useEffect, useRef } from "react";

/**
 * useListKeyboardNav — keyboard navigation for list surfaces.
 *
 * j / ArrowDown  → move to next item in itemIds (stop at end, no wrap)
 * k / ArrowUp    → move to previous item in itemIds (stop at start, no wrap)
 * Enter          → open selected item (calls onSelect with current id if one is highlighted)
 * Escape         → close (calls onClose)
 *
 * EDGE CASES HANDLED:
 * - Focus-in-input guard: keys do NOT fire while the operator is typing in an
 *   INPUT, TEXTAREA, SELECT, or contenteditable element.
 * - Escape coordination: only calls onClose when a selection is active, so it
 *   doesn't double-fire with existing surface Escape handlers that guard on
 *   their own selected state.
 * - Scroll-into-view: after j/k movement, the newly selected row element is
 *   scrolled into view so operators can't lose track of selection in long queues.
 * - enabled gate: caller can pass enabled=false to suspend the hook (e.g. while
 *   a modal is open over the list, or while the detail pane is in edit mode).
 * - prefers-reduced-motion: scrollIntoView uses "instant" behavior under reduced
 *   motion, "smooth" otherwise.
 *
 * CONTRACT:
 *   itemIds  — the CURRENT visible/filtered ordered list (surface-supplied).
 *              Must be a stable reference when the list hasn't changed so the
 *              effect doesn't reattach unnecessarily.
 *   selectedId  — current ?selected= value ("" if nothing selected).
 *   onSelect    — surface's open handler (sets ?selected=, replace:true).
 *   onClose     — surface's close handler (clears ?selected=).
 *   enabled     — default true; surface can disable.
 *   rowSelector — CSS selector to find the row element to scroll into view.
 *                 The row must have data-keyboard-nav-id="{id}" on it.
 *                 Default: `[data-keyboard-nav-id]` matching the new selectedId.
 */

type UseListKeyboardNavOptions = {
  itemIds: string[];
  selectedId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  enabled?: boolean;
  // Optional triage action keys (Focus Mode). Each receives the currently
  // highlighted id. When omitted, that key does nothing — existing list
  // surfaces that only pass select/close are unaffected.
  onPrimary?: (id: string) => void; // Enter — Send (or Bind on unbound)
  onEdit?: (id: string) => void;    // e
  onReject?: (id: string) => void;  // r
  onBind?: (id: string) => void;    // b
};

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

function scrollRowIntoView(id: string): void {
  const el = document.querySelector(`[data-keyboard-nav-id="${CSS.escape(id)}"]`);
  if (!el) return;
  const prefersReducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({
    block: "nearest",
    behavior: prefersReducedMotion ? "instant" : "smooth",
  } as ScrollIntoViewOptions);
}

export function useListKeyboardNav({
  itemIds,
  selectedId,
  onSelect,
  onClose,
  enabled = true,
  onPrimary,
  onEdit,
  onReject,
  onBind,
}: UseListKeyboardNavOptions): void {
  // Keep latest values available inside the event listener without re-attaching
  const stateRef = useRef({
    itemIds,
    selectedId,
    onSelect,
    onClose,
    enabled,
    onPrimary,
    onEdit,
    onReject,
    onBind,
  });
  useEffect(() => {
    stateRef.current = {
      itemIds,
      selectedId,
      onSelect,
      onClose,
      enabled,
      onPrimary,
      onEdit,
      onReject,
      onBind,
    };
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const {
        itemIds,
        selectedId,
        onSelect,
        onClose,
        enabled,
        onPrimary,
        onEdit,
        onReject,
        onBind,
      } = stateRef.current;
      if (!enabled) return;
      if (isInputFocused()) return;

      const key = event.key;

      if (key === "j" || key === "ArrowDown") {
        event.preventDefault();
        if (itemIds.length === 0) return;
        if (!selectedId) {
          // Nothing selected → jump to first
          const first = itemIds[0];
          onSelect(first);
          scrollRowIntoView(first);
          return;
        }
        const idx = itemIds.indexOf(selectedId);
        if (idx === -1 || idx === itemIds.length - 1) return; // already at end, stop
        const next = itemIds[idx + 1];
        onSelect(next);
        scrollRowIntoView(next);
        return;
      }

      if (key === "k" || key === "ArrowUp") {
        event.preventDefault();
        if (itemIds.length === 0) return;
        if (!selectedId) {
          const first = itemIds[0];
          onSelect(first);
          scrollRowIntoView(first);
          return;
        }
        const idx = itemIds.indexOf(selectedId);
        if (idx <= 0) return; // already at start, stop
        const prev = itemIds[idx - 1];
        onSelect(prev);
        scrollRowIntoView(prev);
        return;
      }

      if (key === "Escape") {
        // Only close if something is selected — don't double-fire if the surface
        // has its own Escape handler that already cleared selection.
        if (selectedId) {
          onClose();
        }
        return;
      }

      // ── Triage action keys (Focus Mode) ──────────────────────────────────
      // These only fire when the surface supplied the handler AND a row is
      // highlighted. Ignored (no preventDefault) otherwise so they don't
      // swallow keys on surfaces that don't use them.
      if (!selectedId) return;

      if (key === "Enter" && onPrimary) {
        event.preventDefault();
        onPrimary(selectedId);
        return;
      }
      if ((key === "e" || key === "E") && onEdit) {
        event.preventDefault();
        onEdit(selectedId);
        return;
      }
      if ((key === "r" || key === "R") && onReject) {
        event.preventDefault();
        onReject(selectedId);
        return;
      }
      if ((key === "b" || key === "B") && onBind) {
        event.preventDefault();
        onBind(selectedId);
        return;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []); // empty deps — reads latest state via stateRef
}
