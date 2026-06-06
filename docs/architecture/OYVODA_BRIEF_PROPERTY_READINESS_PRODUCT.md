# Brief — Property-Readiness-Product: trust-console reframe (B now, A-ready later)

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

PRODUCT brick, separate commit from Property-Readiness-Technical (724866d, landed).
Thin reframe — language and framing, NOT new data or logic. Mirrors the B-product /
Guest-Ops-product pattern. The surface is already migrated to Tailwind; this aligns it
with the Operator OS Blueprint as the PROPERTY TRUST CONSOLE.

## The anchoring principle (the one sentence this brick serves)

Properties becomes the **property trust console**, not a knowledge-file manager. The
question the surface answers shifts from "how documented is this property?" to
"**can Oyvoda safely operate this property?**" — framing and intent change; the
underlying completeness data does not.

## The honesty decision (B now, A later) — READ THIS, it shapes the labels

Current per-property labels are completeness-based: `well-documented / has-gaps /
bare-bones`. We are reframing toward READINESS language, but we will NOT overclaim.
True automation readiness needs policy coverage + escalation history + operator-behavior
signals — which DON'T EXIST until the domain-autonomy backend lands. So calling something
"Automation Ready" today, on documentation completeness alone, would be the Properties
version of a fabricated autonomy score. Same discipline as the Home hero placeholder.

Therefore — **decision B (chosen):** reframe to COVERAGE-READINESS labels now, soften so
they don't assert a final autonomy verdict:
- `well-documented` -> **High Readiness** ("Good coverage, few/no gaps, enough context for
  AI to answer most routine questions")
- `has-gaps` -> **Needs Coverage** ("Usable, but missing details that still create review burden")
- `bare-bones` -> **Readiness Blocked** ("Too little reliable context to trust automation")

**Decision A (LATER, when the autonomy backend exists):** these harden into true autonomy
verdicts — `Autonomous / Assisted / Review Only` (or `Automation Ready / Assisted / Blocked`).
That is a future brick, NOT this one.

## CLEAR PATH TO A — the architectural requirement that makes A a one-file swap

Do NOT scatter the three label strings + their descriptions + their tones across the row
chip, grid chip, metric strip, status filter, and expansion. Route ALL of them through a
SINGLE source of truth so the future A-swap is one edit, not a hunt.

Concretely: introduce (or extend) one mapping in routes/Properties/completeness.ts (or a
new readiness.ts beside it) — e.g. a `READINESS_LABELS` record keyed by the existing
completeness label values (`well-documented`/`has-gaps`/`bare-bones`), holding:
{ display, description, tone, filterOptionLabel }. EVERY consumer (CompletenessChip,
MetricChip labels, the status-filter <option> text, PropertyExpansion's chip) reads from
that one record. Keep the underlying completeness *label keys and logic UNCHANGED* — only
the human-facing strings/tones come from the mapping. Then decision A is: point that one
mapping at autonomy-verdict values (and later key it off the autonomy score instead of
completeness). Leave a one-line comment at the mapping: "B (coverage-readiness) now;
hardens to A (autonomy verdicts) when domain-autonomy backend lands — see roadmap."

This is the difference between "A is a clean swap" and "A is a second full reframe." It is
the load-bearing instruction of this brick.

## What to change

1. **Surface framing (header):** SurfaceHeader title stays "Properties" OR becomes
   "Property Readiness" (Blueprint IA name) — use "Property Readiness". Subtitle reframes to
   the trust question: e.g. "Can Oyvoda safely operate each property? Coverage, gaps, and the
   context the AI needs to handle guests without you." Add summaryLine with honest portfolio
   counts: "N high readiness · M need coverage · K blocked" (from the existing portfolioTotals,
   just relabeled). Shell.tsx nav label: "Properties" -> "Property Readiness". Route path
   /app/v2/properties UNCHANGED.
2. **The three labels** via the single mapping (above): High Readiness / Needs Coverage /
   Readiness Blocked, with the descriptions given. The CompletenessChip, the metric-strip
   chips, the status-filter options, and the expansion chip all read the mapping.
3. **Metric strip relabel:** "Well-documented / Has gaps / Bare bones" -> "High readiness /
   Needs coverage / Readiness blocked" (same counts, relabeled via the mapping). Keep "Total
   properties" and "Properties with tagged gaps" as-is.
4. **Light copy alignment:** the completeness TOOLTIP and any "documentation health" phrasing
   shift toward readiness/coverage language. Don't rewrite the upload flow or gap copy — those
   are operational and fine.

## ABSOLUTE scope guards
- NO new data, NO new logic, NO new metrics, NO autonomy score, NO policy/escalation/behavior
  inputs (those are the autonomy backend — decision A). Relabel + reframe only.
- The completeness *calculation*, label *keys* (well-documented/has-gaps/bare-bones), filtering,
  both view modes, both detail paths, the upload/close-the-loop flow — ALL UNCHANGED.
- Route path /app/v2/properties unchanged (rename LABEL only).
- styles.css: this is a reframe; tones may shift via the mapping but should reuse existing token
  utilities. No net styles.css growth; ideally unchanged.
- Do NOT hardcode the three labels anywhere except the single mapping. (A-readiness requirement.)
- preflight false. No localStorage/sessionStorage.

## Done when
- Surface reads as the property trust console: "Property Readiness" title, trust-question
  subtitle, honest readiness summaryLine. Nav label updated; route path unchanged.
- The three labels are High Readiness / Needs Coverage / Readiness Blocked, sourced from ONE
  mapping that every consumer reads. A future A-swap is provably one-file (verify: grep the
  label strings — they should appear only in the mapping).
- Completeness logic/keys, filters, both views, both detail paths, upload flow all behave
  identically to 724866d.
- styles.css not larger. tsc --noEmit clean. preflight false.
- Commit SHA recorded.
- The mapping carries the "B now, hardens to A when autonomy backend lands" comment.
