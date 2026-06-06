import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * useUrlState — bind a typed object of view state to URL query params.
 *
 * The URL is the source of truth for view state that defines "what data am I
 * looking at": active tab, filters, search query, sort, pagination cursor,
 * selected scope, date range, selected row. State that's purely visual
 * (popover open/closed, hover, form draft text) belongs in useState, not here.
 *
 * Behavior:
 *   - Values equal to their defaults are stripped from the URL, so clean
 *     defaults produce clean URLs (no ?tab=action when action is default).
 *   - Coercion follows the type of the default: strings stay strings, numbers
 *     get parsed via Number(), booleans accept "true"/"false"/"1"/"0".
 *     For richer types (enums, unions) pass a string default and validate at
 *     the use site.
 *   - update(partial, { replace: true }) replaces the current history entry
 *     instead of pushing a new one — use for transient updates like row
 *     selection that shouldn't pollute back-button history.
 *
 * Caller contract:
 *   - Define `defaults` at module scope (not inline in the component body).
 *     useUrlState memoizes derived state against the defaults reference, so
 *     an inline object would defeat memoization and re-derive every render.
 *     See route files for the pattern: `const URL_DEFAULTS = { ... }` above
 *     the component, then `useUrlState(URL_DEFAULTS)` inside.
 *
 * The hook returns a tuple of [state, update] mirroring useState semantics so
 * call sites can read state.tab the same way they read a useState value.
 */

type Primitive = string | number | boolean;
type Defaults = Record<string, Primitive>;

type UpdateOptions = {
  replace?: boolean;
};

function coerce<T extends Primitive>(raw: string | null, fallback: T): T {
  if (raw === null || raw === undefined) return fallback;
  if (typeof fallback === "number") {
    const parsed = Number(raw);
    return (Number.isFinite(parsed) ? parsed : fallback) as T;
  }
  if (typeof fallback === "boolean") {
    if (raw === "true" || raw === "1") return true as T;
    if (raw === "false" || raw === "0") return false as T;
    return fallback;
  }
  return raw as T;
}

export function useUrlState<D extends Defaults>(
  defaults: D,
): [D, (patch: Partial<D>, options?: UpdateOptions) => void] {
  const [searchParams, setSearchParams] = useSearchParams();

  // Build the current state by reading each key with type-appropriate coercion.
  // useMemo keyed on the raw search string keeps the state reference stable
  // across re-renders that don't change the URL.
  const state = useMemo(() => {
    const next = {} as D;
    for (const key of Object.keys(defaults) as (keyof D)[]) {
      const fallback = defaults[key];
      const raw = searchParams.get(key as string);
      next[key] = coerce(raw, fallback) as D[typeof key];
    }
    return next;
  }, [searchParams, defaults]);

  const update = useCallback(
    (patch: Partial<D>, options: UpdateOptions = {}) => {
      setSearchParams(
        (current: URLSearchParams) => {
          const next = new URLSearchParams(current);
          for (const key of Object.keys(patch) as (keyof D)[]) {
            const value = patch[key];
            const fallback = defaults[key];
            // Strip defaults to keep URLs clean; serialize everything else.
            if (value === undefined || value === fallback) {
              next.delete(key as string);
            } else {
              next.set(key as string, String(value));
            }
          }
          return next;
        },
        { replace: options.replace ?? false },
      );
    },
    [setSearchParams, defaults],
  );

  return [state, update];
}
