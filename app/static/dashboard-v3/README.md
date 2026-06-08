# Oyvoda Dashboard v3

A greenfield communication interface for Oyvoda's autonomous operations
employee. This is **not** a dashboard — it's the screen where Lanier (the
property manager) is kept informed by a capable colleague.

## The philosophy

- Every line of output is written in **first person**, as if the AI is speaking.
- Every item is tagged with the **channel** it would be delivered through
  (📱 Text · 📧 Email · 🔊 Voice) so the communication style can be reviewed and
  refined before those channels are wired up.
- The writing is the UI. Chrome is kept to a minimum. Dark, calm, typographic.

## One screen, three panels

| Panel | Component | What it is |
| --- | --- | --- |
| **Left — Employee Feed** | `components/EmployeeFeed.tsx` | A chronological, first-person stream of what the AI did, decided, and noticed since the last check-in. |
| **Center — Needs Your Input** | `components/NeedsInput.tsx` | A short, prioritized list of decisions the AI surfaced — *"a quick question before I move forward."* |
| **Right — Context Drawer** | `components/ContextDrawer.tsx` | Opens on click. Shows what I saw, how I thought about it, and what I did or propose — plus approve / override / redirect. |

Selecting any item (left or center) opens it in the drawer. Resolving a
decision logs the result back into the feed, in the AI's voice.

## Running it

```bash
cd app/static/dashboard-v3
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production bundle into dist/
```

Optimized for wide screens (the three-panel command center). Below `lg` the
drawer becomes a slide-over.

## Data

All content is mock and lives in **`src/data/mock.ts`** — a single realistic
morning for a 12-property portfolio. The types in **`src/types.ts`** define the
contract the backend will fill next.

Nothing here talks to the backend yet. When it does, the relevant Oyvoda
endpoints (see `OYVODA_DESIGN_HANDOFF.md`) map roughly as:

- **Feed** ← sessions / journey activity / escalation + work-order events
  (`/app/api/sessions`, `/app/api/escalations`)
- **Needs Your Input** ← pre-booking review queue + autonomy escalations
  (`/app/api/messages?stage=pre_booking`, `/app/api/escalations`)
- **Context Drawer reasoning** ← per-item detail
  (`/app/api/sessions/:id`, inquiry draft/confidence fields)
- **Resolve / override** ← existing approve / reject / send mutations

Also swap `NOW` in `src/lib/time.ts` for `new Date()` once data is live.
