/**
 * Shared list primitives — skeletal interfaces.
 *
 * These types define the contract every dense list surface (Today, Knowledge,
 * Vendors, Settings tables) should consume. Concrete implementations land
 * surface-by-surface as real needs surface.
 *
 * The point of having these types up front is to keep new surfaces from
 * inventing their own list-data shapes ad hoc, which is how 1,000-operator
 * dashboards end up with five subtly-different pagination patterns.
 */

export type CursorListPage<T> = {
  items: T[];
  /**
   * Opaque cursor for the next page. Null when no more pages exist.
   * Backend chooses the format — clients only echo it back as `after`.
   */
  nextCursor: string | null;
  /**
   * Total count when the backend can supply it cheaply. Often null for
   * filtered queries since computing it requires a second scan.
   */
  totalEstimate: number | null;
};

export type CursorListQuery = {
  /** Page size. The backend may clamp; clients should treat the value as a hint. */
  limit: number;
  /** Cursor returned by a prior page. Null/undefined for the first page. */
  after?: string | null;
  /** Free-text search. Debounce at the call site, not here. */
  q?: string;
  /** Arbitrary filters. Each surface defines its own keys. */
  filters?: Record<string, string | number | boolean | null>;
  /** Sort field. Backend defines valid values per surface. */
  sort?: string;
};

export type CursorListFetcher<T> = (
  query: CursorListQuery,
  signal: AbortSignal,
) => Promise<CursorListPage<T>>;

export type CursorListState<T> = {
  items: T[];
  loading: boolean;
  error: Error | null;
  hasMore: boolean;
  totalEstimate: number | null;
};

export type CursorListController<T> = CursorListState<T> & {
  loadMore: () => void;
  refresh: () => void;
};
