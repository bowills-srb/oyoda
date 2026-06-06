# Today — Four-Stage Lifecycle Reshape Spec

**Status:** buildable frontend spec
**Date:** 2026-05-28
**Purpose:** reshape the Today surface from three lifecycle buckets to four, giving far-out booked guests a home and establishing the lifecycle lane the proactive visibility work assumes
**Pairs with:** `docs/scratch/TODAY_PROACTIVE_VISIBILITY_SPEC.md`
**Precedes:** the stage-aware expansion (Deliverable 2 of the proactive visibility spec) — that work depends on this reshape landing first

---

## Why this exists

Today currently classifies sessions into three buckets: `pre_arrival` (check-in within 7 days), `in_stay` (on property), `post_stay` (checked out within 7 days). Anything farther out — a guest who booked for a stay 8+ days away — is classified `out_of_window` and **filtered out of the surface entirely**.

`shared/lifecycle/windows.ts` is explicit that this was deliberate: far-out bookings were reserved for a future "Arrivals" surface, and `classifyForArrivals` throws on purpose so nobody half-builds it.

Product decision (2026-05-28): **do not build a separate Arrivals surface.** Keep the guest lifecycle in one place. The operator thinks in one continuous guest journey, not two pages, and proactive's whole value is getting ahead of a guest's question *before* arrival — hiding far-out guests on another surface weakens that model. So the reserved Arrivals concept becomes a fourth tab inside Today: **pre-arrival**, the quiet planning lane for guests more than 7 days out.

This is a small change. It splits the existing `pre_arrival` bucket at the 7-day line and gives the far half a home. Every other boundary the classifier already enforces stays exactly as-is.

---

## The four stages

| Tab | Boundary | Was |
|---|---|---|
| **Pre-arrival** | `daysUntilCheckIn > 7` (booked, far out) | `out_of_window` — *dropped today* |
| **Arriving** | `1 <= daysUntilCheckIn <= 7` | the current `pre_arrival` bucket, renamed |
| **In-stay** | check-in day through checkout day | unchanged |
| **Post-stay** | day after checkout, within the post-stay window | unchanged |

### Boundaries that DO NOT change

These are preserved exactly from `classifyForToday`:

- **Check-in day is `in_stay`.** A guest arriving today is already an active operational guest. Arrival-day urgency stays with the live stay work, not split into a prep lane. (The backend's `arrival_day` phase is not promoted to a tab; it lives inside in-stay.)
- **Checkout day is `in_stay`.** The guest is still on property until they leave. (The backend's `departure_day` phase lives inside in-stay.)
- **Post-stay starts the day after checkout** and runs for `TODAY_POST_STAY_WINDOW_DAYS`.
- **`phase === 'in_stay'` backend override** still wins over date math.
- All date comparisons stay at UTC midnight via the existing `parseDateUtc` / `floorToUtcDay` helpers.

### The one boundary that changes

The existing `pre_arrival` bucket (`1 <= daysUntilCheckIn <= 7`) is **split at the 7-day line**:

- `1 <= daysUntilCheckIn <= 7` → **arriving**
- `daysUntilCheckIn > 7` → **pre-arrival** (previously `out_of_window`)

There is now no upper bound on pre-arrival from the Today side — a booking 90 days out is a valid pre-arrival session. (Practical volume note in the Scalability section below.)

---

## Landing / default behavior

Today lands on the **live operational center: Arriving + In-stay** — the two high-attention stages (who's coming this week, who's here now). This is where proactive is most active and most likely to need a human.

- **Pre-arrival is NOT the default tab.** It is the calm planning lane and should not visually compete with arriving and in-stay.
- The current default is `in_stay` (`URL_DEFAULTS.tab = "in_stay"` in `routes/Today/index.tsx`). Decision point for the implementer: either keep `in_stay` as the single default tab, or introduce a combined "live" landing showing arriving + in-stay together. **Recommended for v1: keep `in_stay` as the default tab** (smallest change, matches built behavior) and rely on the arriving tab's count badge to pull the operator there when arrivals are pending. A combined live view is a later refinement, not part of this reshape.

Pre-arrival's calmer treatment is a visual/emphasis concern (muted tab, lower-urgency tone) — see "Tone" below.

---

## Implementation — exact changes

### 1. `shared/lifecycle/windows.ts`

Add the fourth bucket to the type and split the classifier.

- Extend `LifecycleBucket`: add `'arriving'`. Final union: `'pre_arrival' | 'arriving' | 'in_stay' | 'post_stay' | 'out_of_window'`.
- Add `TODAY_ARRIVING_WINDOW_DAYS = 7` (the split line). Keep `TODAY_PRE_ARRIVAL_WINDOW_DAYS` but it now means "the arriving window's upper edge" — consider renaming to `TODAY_ARRIVING_WINDOW_DAYS` and updating references, OR keep the old constant name to minimize churn and add a comment. **Recommended: rename to `TODAY_ARRIVING_WINDOW_DAYS`** so the constant name matches the tab it gates; it's referenced in `index.tsx` (empty-copy) and `focusPredicates.ts`, both updated in this spec.
- In `classifyForToday`, after the in_stay checks, replace the single pre_arrival branch with:
  - `daysUntilCheckIn >= 1 && <= 7` → `{ bucket: 'arriving', daysUntilCheckIn }`
  - `daysUntilCheckIn > 7` → `{ bucket: 'pre_arrival', daysUntilCheckIn }`
- `LifecycleClassification.daysUntilCheckIn` is now present for both `arriving` and `pre_arrival`. Update the field comment.
- Leave `classifyForArrivals` as-is (still throws) — we are explicitly NOT building that surface. Add a one-line comment that the Arrivals concept was folded into the Today pre_arrival tab per this spec, so the next reader doesn't resurrect it.

### 2. `routes/Today/focusPredicates.ts`

- Extend `TodayTab`: `"pre_arrival" | "arriving" | "in_stay" | "post_stay"`.
- Define the pre-arrival focus set. Pre-arrival is the quiet planning lane, so its chips are planning-oriented, not urgency-oriented. Recommended set:
  - `pre_arrival`: `["all", "needs_welcome", "unbound"]` — far-out guests who haven't had a welcome, or aren't yet bound to a property/booking. (No `arriving_soon` here — that concept belongs to the arriving tab.)
  - `arriving`: `["all", "arriving_soon", "needs_welcome", "unbound"]` — the *current* `pre_arrival` chip set, moved over wholesale.
  - `in_stay`, `post_stay`: unchanged.
- Note on `arriving_soon`: its predicate currently means `daysUntilCheckIn === 1` (tomorrow's arrivals). That semantic is still correct on the arriving tab. Keep it.
- Add `matchesArrivingFocus` (identical body to the current `matchesPreArrivalFocus`) and a new, narrower `matchesPreArrivalFocus` for the planning chips. Wire both into `matchesFocus`'s tab switch.
- `FOCUSES_BY_TAB` and `FOCUS_LABELS`: add the pre_arrival/arriving entries. No new labels needed if pre-arrival reuses `needs_welcome` / `unbound`.

### 3. `routes/Today/index.tsx`

- `TODAY_TABS`: `["pre_arrival", "arriving", "in_stay", "post_stay"]`. Order matters for tab rendering — pre_arrival first (calm/leftmost) reads as the chronological start of the journey, OR place it last to de-emphasize. **Recommended: order them chronologically — pre_arrival, arriving, in_stay, post_stay** — so the tab strip reads as the guest journey left-to-right, with default selection (not order) doing the de-emphasis work.
- `TAB_LABELS`: `{ pre_arrival: "Pre-arrival", arriving: "Arriving", in_stay: "In stay", post_stay: "Post-stay" }`.
- `TAB_EMPTY_COPY`: add pre_arrival copy. The *old* pre_arrival empty copy ("Sessions with a check-in more than N days out will belong to Arrivals when that surface ships") is now WRONG and must be replaced — those sessions now live in this very tab. New pre_arrival copy: e.g. "No upcoming bookings beyond the next 7 days." New arriving copy: e.g. "No guests arriving in the next 7 days." (the old pre_arrival copy, adjusted).
- `byBucket`: add the `arriving` bucket to the record and its sort. Arriving inherits the *current* pre_arrival sort (escalations → arrival imminence). Pre-arrival sort: by `daysUntilCheckIn` ascending (soonest-approaching first) — the planning lane orders by "who crosses into arriving next."
- `URL_DEFAULTS.tab`: keep `"in_stay"` per the landing decision.
- `coerceTab`: include all four valid tabs.
- `tabCounts` and the header subtitle: extend to four counts. Subtitle becomes something like `"{inStay} in stay · {arriving} arriving · {preArrival} upcoming · {postStay} recently checked out"`.

### 4. `routes/Today/lifecycleLabels.ts`

- `lifecycleStageLabel`: add an `arriving` branch (reuse the current pre_arrival logic — "Arrives tomorrow" / "Arrives in N days"). Add a `pre_arrival` branch for far-out guests — likely a calmer phrasing keyed on the date rather than a countdown, e.g. "Arrives May 30" or "Arrives in 6 weeks", since a day-countdown at 60 days out is noise. **Recommended: pre_arrival shows the check-in date ("Arrives Jul 3"), arriving shows the countdown ("Arrives in 4 days").** The countdown earns its place only when the number is small enough to be actionable.
- `lifecycleStageTone`: add `arriving` → `warning` or `accent` (it's near-term, deserves some weight); `pre_arrival` → `default` (calm). Escalation-danger override stays first.

---

## Tone — keeping pre-arrival calm

Pre-arrival must not compete visually with arriving and in-stay. Concrete treatments:

- Default tone `default` (neutral/muted), never `danger`/`warning` unless an escalation forces it.
- Stage label is a date, not a ticking countdown.
- Not the default tab; reached deliberately.
- Its focus chips are planning verbs (needs welcome, unbound), not urgency verbs (escalations, due).

The operator should feel pre-arrival is "the guests on the books I can plan ahead for," not "more fires to fight."

---

## Scalability note

The current Today route fetches with `limit=50` / `limit=200` and filters client-side (flagged in `docs/TODAY_SCALABILITY_WORK_ITEM.md`). Adding pre-arrival *increases the row count* materially: with no upper bound, every future booking is now an in-window session. For Beach Habitats (~50 units) this is fine. But this reshape makes the scalability item more pressing sooner, because pre-arrival can be the largest bucket by far (a property booked months out has many pre-arrival sessions and few in-stay).

Two mitigations, in order of preference:
1. **Lazy-load pre-arrival.** Since pre-arrival is not the default tab, its sessions don't need to be in the initial fetch. Fetch arriving + in_stay + post_stay on load; fetch pre_arrival only when the tab is first opened. This keeps the default landing fast and bounds the initial payload.
2. If staying single-fetch for v1 simplicity, raise the limit and add a comment pointing at the scalability work item, accepting that pre-arrival counts may be approximate at high volume.

**Recommended for v1: option 1 (lazy-load pre-arrival)** — it's the change that ages best and matches the "pre-arrival is the quiet lane" framing (you don't pay for it until you look at it).

---

## What this spec does NOT do

- Does not build a separate Arrivals surface (explicitly folded into Today).
- Does not promote `arrival_day` or `departure_day` to their own tabs (they stay inside in_stay).
- Does not touch the proactive payload, runtime, or cadence.
- Does not build the stage-aware proactive expansion — that's the proactive visibility spec's Deliverable 2, which runs *after* this reshape so its four stages are real.
- Does not change any backend code. This is entirely within `dashboard-v2/src`.

---

## Sequence

1. Build the collapsed-row proactive indicator (proactive visibility spec, Deliverable 1) — stage-agnostic, can land in parallel with or before this reshape.
2. **Build this reshape** — four tabs, the classifier split, lazy-loaded pre-arrival.
3. Build the stage-aware proactive expansion (proactive visibility spec, Deliverables 2–3) against the now-real four stages.
4. Later: proactive runtime consolidation, then the forward-plan `scheduledTouches[]` field.
