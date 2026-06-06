import type {
  CursorListController,
  CursorListFetcher,
  CursorListQuery,
} from "./types";

/**
 * useCursorList — cursor-paginated, abort-aware list hook.
 *
 * NOT IMPLEMENTED YET. This file exists so new surfaces import a stable name
 * and don't invent their own pagination patterns. The first surface that
 * actually needs paginated data lands the real implementation here. Until
 * then, calling this hook throws, which is the right failure mode: silent
 * stubs let surfaces ship without realizing they're broken.
 *
 * When implemented, the hook will:
 *   - Hold an array of pages keyed by cursor, concatenated for rendering
 *   - Abort in-flight fetches on query change via AbortController
 *   - Expose loadMore() / refresh() and {loading, error, hasMore}
 *   - Reset on query identity change (filters/search/sort)
 *   - Never reach into the fetcher's transport — fetcher takes (query, signal)
 */

export function useCursorList<T>(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _fetcher: CursorListFetcher<T>,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _query: CursorListQuery,
): CursorListController<T> {
  throw new Error(
    "useCursorList is not implemented yet. The first surface that needs " +
      "paginated data should land the implementation in this file.",
  );
}
