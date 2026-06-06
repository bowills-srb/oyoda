# Session Resume — 2026-05-05

> **Superseded for sequencing purposes by
> `docs/IMPLEMENTATION_QUEUE_2026_05_05.md` (added 2026-05-05 PM).**
>
> The Workstreams 1-6 below remain tracked, but they have been
> consolidated with the deferred Sessions 10-13 brain build queue and
> the 2026-05-05 audit findings into a single sequenced work order in
> the implementation-queue doc. Read that file first.
>
> The 2026-05-05 audit produced one load-bearing finding not anticipated
> by the workstream framing below: the messaging brain's
> `_compose_response` at
> `app/services/messaging_brain/orchestrator.py` line 709 is currently
> a string concatenator, not an LLM composer. The Phase 4 composer the
> design assumed has not been built. Until it lands, brain runtime is
> structurally narrower than the legacy path. This is not an
> architecture choice — it is a deferred build step.
>
> The implementation-queue doc sequences the composer work (Phase C)
> and the surgical brain-context wins it depends on (Phase B) ahead of
> the safety/quality workstreams below. Workstreams 1-6 are mostly
> absorbed into Phases D and F of that doc.

---

This note is the session-opening artifact for the next audit pass
after the 2026-05-04 addendum. It turns the corrected framing into a
work order so the next session starts from the updated understanding
rather than the preliminary one in
`docs/PIPELINE_COORDINATION_OBSERVATIONS_2026_05_03.md`.

Read in this order:

1. `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md`
2. `docs/PIPELINE_COORDINATION_OBSERVATIONS_2026_05_03.md`
3. Supporting decision docs only as needed

## Session-opening sequence

1. Re-anchor on the addendum reframes.
   The key correction is that the main safety question is not
   "regenerate bypasses the gate" but "what does the model do when
   grounding is thin, and what actually constrains that behavior?"

2. Preserve the resolved items as closed.
   Do not reopen §6.3 or §6.6 unless regressions are observed.
   `ecbbfd2` and `3599502` closed those concrete parser/property-name
   issues.

3. Treat the "cross-eyed child" seam framing as a diagnostic tool, not
   just a metaphor.
   The two strongest examples so far are stale worker deployment and
   decoded-body-vs-RFC-2822 contract mismatch.

4. Work the remaining questions in a tight order so later threads do
   not depend on stale assumptions.

5. Before resuming the original workstreams, read
   `docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md`.
   The 2026-05-05 investigation pivoted away from pre-booking draft
   generation and toward an upstream Gmail / messaging-brain /
   rich-context trigger on malformed Airbnb automation-shaped traffic.
   Do not restart the trace in `generate_inquiry_draft(...)`.

## Active workstreams

### Workstream 1 — Thin-grounding safety characterization

Goal: characterize model behavior when property grounding is weak or
missing, independent of whether the hold-draft heuristic happens to
fire.

Why first: this is the corrected core safety question and the Jackie
Lee case is the clearest motivating example.

Concrete questions:

- Under what input shapes does the model produce confident factual
  claims from absent property grounding?
- Which warnings, policy flags, or draft-source markers remain visible
  to operators in those cases?
- How often does the current hold-draft heuristic mask the behavior vs.
  miss it vs. over-fire on harmless cases?

Suggested output:

- A small matrix of representative inquiry shapes
- For each: grounding available, gate result, draft result, operator UI
  state
- A conclusion framed around actual failure behavior, not heuristic
  symmetry alone

### Workstream 2 — Airbnb reply-channel mechanics

Goal: determine whether Airbnb inquiry replies can actually traverse
Oyvoda's Gmail-send path, and if so for which message classes.

Concrete questions:

- Does `reply.airbnb.com` accept replies for pre-booking inquiries, or
  only some Airbnb thread types?
- What reply target does `_adapt_ota_inquiry` produce for Airbnb rows?
- Does `_is_platform_automation_email` suppress valid Airbnb reply
  targets?
- If Airbnb replies do not reliably surface in Gmail, how should State
  D ("operator already replied") be modeled for Airbnb specifically?

Why it matters: if the assumed reply path is wrong, read-state logic,
thread-state logic, and send-path expectations all diverge by channel.

### Workstream 3 — Intake classification hygiene

Goal: reduce non-guest traffic entering `pre_booking_inquiries` and
separate "who sent this" from "what kind of message is this."

Near-term step:

- Add a sender/domain blocklist or allowlist pass for known non-guest
  patterns, especially operator-owned domains and common marketing /
  noreply senders.

Longer-term step:

- Split intake classification into independent channel and intent
  classification before routing into guest-inquiry flows.

Why it matters: the current stream is materially mixed, and operator
domain traffic being treated as potential guest traffic is a real
misrouting risk.

### Workstream 4 — Thread-state model by channel

Goal: make Option B's thread-state assumptions channel-aware instead of
implicitly Gmail-uniform.

Focus:

- Reconcile Vrbo vs Airbnb reply visibility
- Define what counts as "operator already replied" when replies may
  happen on-platform
- Keep state semantics explicit if channel behavior differs

This work depends partly on Workstream 2, but the modeling questions
can be sketched in parallel.

### Workstream 5 — Hold-rate recheck with corrected methodology

Goal: re-run aggregate hold-rate analysis without using
`parser_source = 'generic_gmail_parser'` as a stand-in for parser
failure.

Method caveat:

- Direct-channel guest emails legitimately route through the generic
  parser, so generic-parser rows need channel-aware filtering before
  they can be used to interpret hold-rate distributions.

Target date:

- 2026-05-11

### Workstream 6 — Deployment seam reliability

Goal: prevent cases where `oyvoda` and `oyvoda-worker` diverge because
only one service is running the new code.

Questions:

- What deployment step allowed the app-tier read-state fix to land
  while worker code remained stale?
- Is there a missing coupled deploy, version check, or smoke test
  across the two services?
- What is the smallest reliable guardrail that makes this seam visible
  before operators notice behavioral drift?

Why it matters: this was a concrete validation of the seam-first
diagnostic frame.

## Rollback ordering

If time is short or the session needs to narrow scope, de-scope in
this order:

1. Keep Workstream 1.
2. Keep Workstream 2 if Airbnb behavior is still unknown.
3. Keep Workstream 3's near-term sender hygiene even if the
   architectural intake redesign slips.
4. Push Workstream 4 modeling after Workstream 2 if needed.
5. Leave Workstream 5 on its scheduled date unless it becomes newly
   blocking.
6. Keep Workstream 6 as a deployment follow-up, but let it trail the
   user-facing safety and routing questions if sequencing pressure is
   high.

## Closed items from prior session

- §6.3 resolved by `ecbbfd2`
- §6.6 resolved by `3599502`
- §6.1 reframed and conditionally closed as Outcome B, with heuristic
  noise explicitly documented

## Reminder

Do not use the Jackie Lee case as standalone proof of
regenerate-path-gate bypass. Use it as evidence of confident
fabrication under thin grounding unless new evidence shows the gate
behavior itself is the decisive factor in that case.
