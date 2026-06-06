/**
 * Escalations route — lazy default export consumed by Router.tsx.
 *
 * Wrapped in Suspense at the router level; EscalationsRoute itself uses
 * useSuspenseQuery so the loading skeleton falls through to RouteSuspense.
 */
export { default } from "./EscalationsRoute";
