/**
 * App.tsx — REMOVED in the shell-split commit.
 *
 * The single-file App that lived here was replaced by:
 *   - src/app/Router.tsx   — route table and lazy boundaries
 *   - src/app/Shell.tsx    — sidebar, brand, primary nav, operator menu
 *   - src/routes/PreBooking/PreBookingRoute.tsx — the extracted surface
 *
 * If anything still imports from this file, that's a stale reference.
 * Delete the import; point it at the new module above.
 *
 * This file remains so the diff is reviewable. A follow-up commit can
 * delete the file outright once we've confirmed no stragglers.
 */
export function App(): never {
  throw new Error(
    "App from src/App.tsx is removed. Use the router in src/app/Router.tsx. " +
      "If you got here from a stale import, switch to: " +
      "import { Router } from './app/Router'.",
  );
}
