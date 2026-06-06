# Brief — Guest-Ops-Product: rename Today -> Guest Operations (thin, no structural change)

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

PRODUCT brick, separate commit from Guest-Ops-Technical (6ddfde5, landed). Mirrors
B-product exactly. This is thin — the session-first architecture is already correct and
already migrated to Tailwind. This brick only aligns the NAME and terminology with the
Operator OS Blueprint IA. NO structural, logic, or data change.

## Context (verified against the post-6ddfde5 file)

Today/index.tsx is already Tailwind, already session-first, and the SurfaceHeader already
has summaryLine wired (the aiSummary line). So almost nothing needs to change — this is a
rename pass, not a build.

## What to change

### 1. Surface name: "Today" -> "Guest Operations"
- SurfaceHeader title in Today/index.tsx: `title="Today"` -> `title="Guest Operations"`.
- Shell.tsx NAV_ITEMS: the "Today" nav label -> "Guest Operations". Route path
  /app/v2/today UNCHANGED (label only, no router/redirect churn — same as the Inquiry
  Operations rename kept /app/v2/prebooking).

### 2. Light terminology alignment (optional, low-touch)
The header subtitle and aiSummary are already operationally framed ("N in stay · M
arriving · ...", "AI support today: ..."). Leave them — they already read as guest
operations, not messages. Only adjust a string if it literally says "Today" in a way that
now reads oddly next to the "Guest Operations" title. Do NOT invent new copy or metrics.

### 3. Nothing else
The lifecycle tabs (Pre-arrival/Arriving/In stay/Post-stay), focus chips, priority cards,
session expansion, sort logic — all stay exactly as they are. This brick does not touch them.

## ABSOLUTE scope guards
- Label/name only. NO structural change, NO logic change, NO data change, NO new metrics,
  NO autonomy framing, NO layout change.
- Route path stays /app/v2/today (rename the LABEL, not the route).
- styles.css UNCHANGED (this brick adds/deletes no CSS). If it changes, something is wrong.
- Do NOT touch the session expansion, the tabs, or any of the Today/* helper modules.
- preflight false. No localStorage/sessionStorage.

## Done when
- Surface reads as "Guest Operations" (SurfaceHeader title + Shell nav label).
- Route path /app/v2/today unchanged.
- Lifecycle tabs and all behavior identical to 6ddfde5.
- styles.css unchanged. tsc --noEmit clean. preflight false.
- Commit SHA recorded (separate from 6ddfde5).
