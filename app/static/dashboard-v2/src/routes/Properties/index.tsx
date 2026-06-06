/**
 * Properties route — default export for lazy loading.
 *
 * The router in src/app/Router.tsx lazy-imports `../routes/Properties` and
 * expects the default export to be the route component. This file makes
 * PropertiesRoute the default so that wiring works.
 */
export { default } from "./PropertiesRoute";
