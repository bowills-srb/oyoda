import React from "react";

/**
 * VirtualTable — windowed table renderer for long lists.
 *
 * NOT IMPLEMENTED YET. Renders a placeholder so callers can wire it in,
 * but doesn't actually virtualize anything. The first surface that needs
 * to render >1,000 rows (likely Today or large-operator Vendors) lands the
 * real implementation here.
 *
 * Decision points the real implementation has to settle:
 *   - Fixed row height vs. measured: fixed is faster and works for our
 *     row designs. Start with fixed.
 *   - Use @tanstack/react-virtual or write a tight in-house windowing layer.
 *     React-virtual is well-trodden; bringing it in is a small dependency
 *     decision worth making deliberately when the first caller arrives.
 *   - Scroll restoration on route change: needs explicit handling so the
 *     URL-state pattern doesn't lose scroll position between back/forward.
 */

export type VirtualTableProps<T> = {
  items: T[];
  rowHeight: number;
  renderRow: (item: T, index: number) => React.ReactNode;
  empty?: React.ReactNode;
  /** Aria label for the underlying scroll region. */
  ariaLabel?: string;
};

export function VirtualTable<T>({
  items,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  rowHeight,
  renderRow,
  empty,
  ariaLabel,
}: VirtualTableProps<T>) {
  if (!items.length && empty !== undefined) {
    return <>{empty}</>;
  }
  // Placeholder: render everything. Replace with windowed rendering when the
  // first caller actually needs it. Not silently lying about virtualization
  // here so dev tools / row counts make the "not yet implemented" obvious.
  return (
    <div role="region" aria-label={ariaLabel} data-virtual-table="placeholder">
      {items.map((item, index) => (
        <React.Fragment key={index}>{renderRow(item, index)}</React.Fragment>
      ))}
    </div>
  );
}
