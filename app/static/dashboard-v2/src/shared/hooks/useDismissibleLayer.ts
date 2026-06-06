import { useEffect, useRef } from "react";

/**
 * Shared dismissal behavior for anchored overlays like menus and popovers.
 * Keeps outside-click and Escape handling consistent without forcing a
 * heavyweight overlay library into the app mid-migration.
 */
export function useDismissibleLayer<T extends HTMLElement>(
  open: boolean,
  onClose: () => void,
) {
  const anchorRef = useRef<T>(null);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (anchorRef.current && target && !anchorRef.current.contains(target)) {
        onClose();
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  return anchorRef;
}
