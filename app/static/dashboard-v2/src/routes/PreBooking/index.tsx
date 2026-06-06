// Re-export so the router can do `import PreBookingRoute from ".../PreBooking"`
// and the test/storybook entry points have a stable index file to hit. Kept
// as a thin re-export so the route's own implementation file
// (PreBookingRoute.tsx) is what readers open when chasing component changes.
export { default } from "./PreBookingRoute";
