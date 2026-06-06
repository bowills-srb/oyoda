import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useRouteError } from "react-router-dom";

import { Shell } from "./Shell";
import { SurfaceHeader } from "../components/system/SurfaceHeader";
import { Button } from "../components/ui/button";

/**
 * Router — top-level route table for /app/v2/*.
 *
 * Most surfaces lazy-load via React.lazy() so first paint only ships the
 * active route's bundle. Pre-Booking remains eager because it is still one of
 * the heaviest-used operator views, but the default landing is Today so v2
 * opens directly into the live operations queue.
 *
 * The basename matches the server-side mount: operator_app.py serves the
 * same SPA index for /app/v2 and /app/v2/{path:path}, so any client URL
 * under /app/v2/ is handled here.
 *
 * The 404 fallback redirects to the default route rather than rendering an
 * error page. For internal operator surfaces, a friendly bounce to "where
 * you probably meant to go" is better UX than a not-found page.
 */

const HomeRoute = lazy(() => import("../routes/Home"));
const PreBookingRoute = lazy(() => import("../routes/PreBooking"));
const EscalationsRoute = lazy(() => import("../routes/Escalations"));
const TodayRoute = lazy(() => import("../routes/Today"));
const PropertiesRoute = lazy(() => import("../routes/Properties"));
const KnowledgeRoute = lazy(() => import("../routes/Knowledge"));
const VendorsRoute = lazy(() => import("../routes/Vendors"));
const SettingsRoute = lazy(() => import("../routes/Settings"));
const ComponentsRoute = lazy(() => import("../routes/Components"));

function RouteSuspense({ children }: { children: React.ReactNode }) {
  // Minimal loading state. Each route also shows its own skeleton/empty
  // once it mounts; this fallback only covers the bundle download window.
  //
  // Renders the surface body only — no wrapping .app-frame. The Shell
  // already owns the outer grid (sidebar + outlet); wrapping here would
  // nest .app-frame inside .app-frame and re-introduce the double-gutter
  // bug the route components were just fixed for.
  return (
    <Suspense
      fallback={
        <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
          <SurfaceHeader title="Loading…" />
        </main>
      }
    >
      {children}
    </Suspense>
  );
}

function RouteError() {
  const error = useRouteError();
  const errorLike = error as { message?: unknown; status?: unknown } | null;
  const status =
    errorLike && typeof errorLike.status === "number"
      ? errorLike.status
      : undefined;
  const message =
    error instanceof Error
      ? error.message
      : errorLike && typeof errorLike.message === "string"
        ? errorLike.message
        : "This surface failed to load.";
  const isAuth = status === 401 || /401|not authenticated|unauthorized/i.test(message);

  return (
    <main className="grid grid-rows-[auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto">
      <SurfaceHeader
        kicker="Recovery"
        title={isAuth ? "Your session ended" : "This surface hit an error"}
        subtitle={
          isAuth
            ? "Sign in again to return to your operator workspace."
            : "The rest of the workspace is still available in the sidebar."
        }
      />
      <section className="px-7 py-6">
        <div className="max-w-2xl rounded-lg border border-hairline bg-raised p-6 shadow-[0_8px_24px_rgba(15,23,42,0.08)]">
          <p className="m-0 text-sm leading-6 text-secondary">{message}</p>
          <div className="mt-5 flex gap-2.5">
            {isAuth ? (
              <Button asChild size="sm">
                <a href="/app">Sign in</a>
              </Button>
            ) : (
              <Button size="sm" type="button" onClick={() => window.location.reload()}>
                Reload this surface
              </Button>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

const router = createBrowserRouter([
  {
    path: "/app/v2",
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      // Default landing: Today. /app/v2 redirects to /app/v2/today so the
      // authenticated handoff opens directly into guest operations.
      { index: true, element: <Navigate to="/app/v2/today" replace /> },
      {
        path: "home",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <HomeRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "prebooking",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <PreBookingRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "escalations",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <EscalationsRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "today",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <TodayRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "properties",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <PropertiesRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "knowledge",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <KnowledgeRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "vendors",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <VendorsRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "settings",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <SettingsRoute />
          </RouteSuspense>
        ),
      },
      {
        path: "components",
        errorElement: <RouteError />,
        element: (
          <RouteSuspense>
            <ComponentsRoute />
          </RouteSuspense>
        ),
      },
      // Anything else under /app/v2/ falls back to Today. Better than
      // a 404 for internal surfaces where deep links may go stale across
      // renames.
      { path: "*", element: <Navigate to="/app/v2/today" replace /> },
    ],
  },
]);

export function Router() {
  return <RouterProvider router={router} />;
}
