/**
 * QueueReview.jsx — RETIRED
 *
 * This file was a design-system reference page written against the wrong
 * frontend codebase (the deprecated `oyvoda-v10.jsx` React monolith). It
 * was never wired into production and should not be referenced by any
 * subsequent design work.
 *
 * The active operator dashboard lives in `app/static/dashboard/` and uses
 * the vanilla-JS section-module pattern:
 *   - app/static/dashboard/js/router.js      — view navigation
 *   - app/static/dashboard/js/api.js         — typed fetch wrappers
 *   - app/static/dashboard/js/adapters.js    — payload normalization
 *   - app/static/dashboard/js/state.js       — pub/sub store
 *   - app/static/dashboard/js/sections/*.js  — feature modules
 *
 * The new design system (see docs/architecture/DESIGN_SYSTEM.md) gets
 * applied by:
 *   1. Replacing the dark navy + amber tokens in
 *      app/static/dashboard/styles/tokens.css with the light-mode-first
 *      tokens from the spec.
 *   2. Adding primitive component styles to
 *      app/static/dashboard/styles/dashboard.css (Button, Badge, etc.).
 *   3. Redesigning section modules in place (e.g. sections/messages.js
 *      for the pre-booking queue), not building parallel React files.
 *
 * Retired by Ship 7 / Frontend Retirement, May 2026.
 */
