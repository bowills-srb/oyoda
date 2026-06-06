# Spooky/Gate-Block Verification Under LLM-First Path

Date: 2026-05-27
Tenant under test: Beach Habitats (`e07980b2-a990-4b24-91d1-c8cb71ab70e1`)
Status: plan only, no code change yet
Anchor: [docs/scratch/SPOOKY_LANE_GATE_CODE_AUDIT.sql](SPOOKY_LANE_GATE_CODE_AUDIT.sql)
Discipline: [docs/architecture/MIGRATION_DISCIPLINE.md](../architecture/MIGRATION_DISCIPLINE.md) — Principles 3 (audit before fix), 4 (route outcomes must be queryable truth), and 6 (hybrid states must be honest in UI)

## Purpose

Verify, on real production traffic under the LLM-first intake path, whether
the Spooky Lane class of failure (gate-code question incorrectly date-gap-blocked,
answer existed in KB but was never retrieved) actually resolves itself, or
whether a targeted code fix is still needed.

This phase is **verification, not fix** in its first stage. The fix shape is
documented in the second half of this doc and only lands if verification
confirms it's still needed.

## Root cause confirmation from code reading

The original Spooky audit told us:
- Property-scoped KB had the answer (row `38bb1d2d-f5e8-4d82-b568-e2681c2c0adf`, topic_id `check_in_process`)
- Inquiry was classified as `booking_inquiry / availability`
- `confidence_source = gap_blocked`
- `blocked_by_gap_topics = {requested_dates}`
- `used_kb_chunks = false`
- The brain composed a "Which dates are you considering?" deflection

Reading the actual brain code sharpens this to a specific mechanism. The
chain is:

1. **Intake classifier emits topic `booking_inquiry`** for the original
   inquiry (deterministic prefilter classification at 0.53 confidence).
2. **Agent router dispatches to
   [app/services/messaging_brain/agents/booking_inquiry_agent.py](../../app/services/messaging_brain/agents/booking_inquiry_agent.py),
   `_handle_availability`.**
3. That method checks `context.reservation_facts.requested_check_in`
   and `requested_check_out`. If either is missing, it unconditionally
   emits:
   ```python
   AgentDecision(
       ...
       missing_info=["requested_dates"],
       recommended_action=RecommendedAction.CLARIFY,
       draft_text="Thanks for your interest! Could you share the dates you’re considering...",
   )
   ```
4. **In
   [app/services/messaging_brain/pre_booking_lifecycle.py](../../app/services/messaging_brain/pre_booking_lifecycle.py),
   `_brain_missing_knowledge_topics` collects `requested_dates`** from the
   audit record.
5. **`execute_pre_booking_lifecycle` lines 365-371** set
   `confidence_source = "gap_blocked"` because
   `decision_stage.missing_knowledge_topics` is non-empty, regardless of
   whether the guest actually asked about availability.
6. The held draft (the date-deflection text) is what the operator sees.
7. **KB retrieval never runs** because the agent already short-circuited
   into the date-gap branch.

So the precise failure is: **the intent classification routed a gate-code
question to the wrong specialist agent**, and that agent has no awareness
that the original message was about access, not dates.

## Why LLM-first might fix this

Codex's replay showed:
- Deterministic: `topic = booking_inquiry`, confidence 0.53
- Groq: `topic = access`, sub-intents `gate_code` and `timing`, confidence 0.85

If the LLM-first intake correctly classifies as `access`, the agent router
dispatches to a different specialist
(`app/services/messaging_brain/agents/access_agent.py`, presumably) that
has different evidence requirements and doesn't unconditionally demand
`requested_dates`. Then KB retrieval against the property-scoped
`check_in_process` topic should succeed, and the brain composes a real
grounded answer.

But this is a hypothesis from code reading, not a verified production
outcome. **We need to confirm it actually happens on real traffic before
declaring this class resolved.**

## Verification plan

### Step 1 — Synthetic replay against LLM-first intake (no flag flip needed)

For 3-5 known Spooky-class messages from production (recent
`confidence_source = gap_blocked` rows with `blocked_by_gap_topics = {requested_dates}`
that are actually about access/gate codes, not real availability questions),
run the message text through the LLM-first intake classifier in isolation
and capture:

- What topic does Groq return?
- What sub-intents and confidence?
- Does the topic route to a non-`booking_inquiry` specialist agent?

This is a small Python script, not a full dispatch run. It tests the
classifier output for the specific message texts that previously failed.

**SQL to source candidates:**

```sql
SELECT
    draft_id,
    received_at,
    guest_name,
    property_external_id,
    LEFT(message_text, 400) AS message_preview,
    blocked_by_gap_topics,
    confidence_source,
    intent
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND confidence_source = 'gap_blocked'
  AND 'requested_dates' = ANY(blocked_by_gap_topics)
  AND received_at > NOW() - INTERVAL '30 days'
ORDER BY received_at DESC
LIMIT 20;
```

Then visually inspect message texts and pick 3-5 that are clearly NOT
availability questions — examples:
- "What time do we get the gate code?"
- "How does check-in work?"
- "Can you confirm the door code for us?"
- "When will I receive the access instructions?"

Skip messages that are genuinely availability questions (those legitimately
need dates and the gap is the right behavior).

### Step 2 — Full dispatch replay (depends on Phase 1)

Once Phase 1 brain-primary replay infrastructure exists (see
[BRAIN_PRIMARY_REPLAY_PLAN.md](BRAIN_PRIMARY_REPLAY_PLAN.md)), one of the
selected cases there is already a Spooky-class message (Case 3 in that
plan). The end-to-end output will confirm:
- Topic classification under LLM-first
- Specialist agent invoked
- KB retrieval attempted
- Final draft text and `confidence_source`

This is the same replay infrastructure, just with focused verification
criteria for the Spooky class.

### Step 3 — Production observation (after `brain_prebooking_lifecycle_primary` flips)

Once Phase 1 concludes with the flag flipped, the Spooky verification
becomes a daily query for 7 days:

```sql
SELECT
    DATE_TRUNC('day', received_at) AS day,
    confidence_source,
    COUNT(*) AS rows,
    COUNT(*) FILTER (WHERE 'requested_dates' = ANY(blocked_by_gap_topics)) AS date_gap_count
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND received_at > NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 1 DESC, rows DESC;
```

If `gap_blocked` with `requested_dates` keeps appearing at the same rate
as before (proportional to inbound volume), the LLM-first flip didn't
solve this class and a code fix is needed. If the rate drops meaningfully
(say >70% reduction), the class is largely resolved.

## Pass / fail decision rubric

Three outcomes possible, each pointing to a different next step:

### Outcome A — LLM-first fully resolves the class

Evidence:
- Groq classifies the Step 1 messages as `access` (or similar non-`booking_inquiry` topics)
- Step 2 replay produces real KB-grounded drafts, no `gap_blocked` rows
- Step 3 production observation shows the `gap_blocked + requested_dates`
  rate drops to ~0

**Decision:** No code fix needed. Document the resolution in this doc and
close the Spooky workstream. Add the query in Step 3 to a weekly health
check.

### Outcome B — LLM-first partially resolves the class

Evidence:
- Groq classifies some Spooky-class messages correctly but not others
  (e.g. clear "what time do we get the gate code" works, but ambiguous
  phrasing like "what about checking in?" still routes to `booking_inquiry`)
- Step 3 production observation shows the rate drops but doesn't approach zero

**Decision:** Code fix needed for the residual cases. The fix shape is
documented below.

### Outcome C — LLM-first doesn't resolve the class

Evidence:
- Groq still routes most Spooky-class messages to `booking_inquiry`
- Or routes correctly but the agent still date-gaps anyway
- Production observation shows no meaningful rate drop

**Decision:** Code fix needed at the agent layer, possibly combined with
intent classifier prompt improvements. The fix shape below applies in
full.

## Code fix shape (only lands if Outcome B or C)

Two surgical changes, both targeted at the date-gap-block logic. Do NOT
write this code until verification confirms it's needed.

### Change 1 — `booking_inquiry_agent.py`: be intent-aware before date-gapping

Current code in `_handle_availability` unconditionally emits
`missing_info=["requested_dates"]` if dates are missing. This is correct
when the message is genuinely about availability ("are you open Aug 23-28?")
but wrong when the message arrived at this agent because of misclassification
and is actually about access, check-in process, etc.

The fix: before emitting `missing_info=["requested_dates"]`, check whether
the message text actually contains availability signals. If it doesn't,
hand off to a different agent or return a different decision shape.

```python
async def _handle_availability(
    self,
    *,
    message: InboundGuestMessage,
    context: GuestContextBundle,
    db_session: Any,
) -> AgentDecision:
    text = message.text or ""

    # Phase 3 fix: only emit requested_dates as a gap when the message
    # actually asks an availability question. If the classifier routed
    # here from a non-availability signal (gate codes, check-in process,
    # etc.), surface that mismatch as a routing audit flag rather than
    # blocking the inquiry on dates that aren't relevant.
    if not _matches_any(text, _AVAILABILITY_PATTERNS):
        logger.info(
            "[BookingInquiryAgent] non-availability message routed here; "
            "deferring to downstream specialist instead of date-gap-blocking. "
            "text_preview=%r property_code=%s",
            text[:100],
            context.property_code or message.property_code,
        )
        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=_NO_CONTEXT_CONFIDENCE,
            answer_summary="message routed here without availability signals; deferring",
            evidence_used=[],
            missing_info=[],  # NOT requested_dates
            risk_flags=["intake_routing_uncertain"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text="",  # downstream specialist or composer fills in
            module_events=[],
        )

    # Existing logic continues here...
    evidence = self._cite_evidence(
        context,
        "reservation_facts.requested_check_in",
        "reservation_facts.requested_check_out",
    )
    check_in = _parse_iso_date(context.reservation_facts.get("requested_check_in"))
    check_out = _parse_iso_date(context.reservation_facts.get("requested_check_out"))

    if not check_in or not check_out:
        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=_NO_CONTEXT_CONFIDENCE,
            answer_summary="availability question missing requested dates",
            evidence_used=evidence,
            missing_info=["requested_dates"],
            # ... rest unchanged
        )
```

This is the smallest possible change that preserves correct date-gap
behavior for real availability questions while not date-gapping
misclassified messages. The cost is that misclassified messages might
get an empty draft and need operator review — but operator review is
the right outcome here, not a confidently wrong date-gap deflection.

### Change 2 — `pre_booking_lifecycle.py`: don't tag as `gap_blocked` when no real gap

The current behavior in `execute_pre_booking_lifecycle` lines 365-371:

```python
elif decision_stage.missing_knowledge_topics:
    resolved_confidence_source = "gap_blocked"
```

If Change 1 lands, `missing_knowledge_topics` will only be non-empty when
there's a real KB gap, not when an agent date-gaps a misclassified message.
But to be defensive (Principle 4: route outcomes must be queryable truth),
also consider distinguishing "the agent flagged this as needing more info"
from "the system has no answer."

Option A (minimal): no change to `pre_booking_lifecycle.py`. Change 1
alone makes `missing_knowledge_topics` empty for misclassified Spooky-class
messages, so they naturally fall through to `confidence_source = "model_composer"`.

Option B (defensive): add an explicit `confidence_source = "routing_uncertain"`
when the agent emits `risk_flags=["intake_routing_uncertain"]`. This makes
the audit even more legible at query time.

Codex picks A or B after verifying Change 1 works.

### Change 3 (optional) — KB retrieval should happen even on uncertain routing

The deeper question is whether the brain should attempt KB retrieval against
the property's scoped knowledge when the agent isn't confident it routed
to the right specialist. Currently the agent's early return short-circuits
KB retrieval entirely.

This is a larger refactor and is **deferred** unless Outcomes B/C show
that even after Changes 1+2, the brain still misses KB answers that exist
on the property. Don't bundle this with the smaller fixes.

## Verification criteria for the code fix (if it lands)

After Change 1 deploys:

1. The Step 3 production query shows `gap_blocked + requested_dates` rate
   continues dropping or holds at ~0
2. New `risk_flags = "intake_routing_uncertain"` rows appear at a low rate
   (single digits per week)
3. No regression: genuine availability questions still produce
   `gap_blocked + requested_dates` and the "Which dates are you considering?"
   draft as before
4. Spooky Lane historical replay produces a non-empty, KB-grounded draft
   when re-run through dispatch
5. Operator-visible behavior change: held drafts for misclassified
   Spooky-class messages now arrive with empty draft text and a routing
   uncertainty flag, rather than a wrong-domain deflection

## Rollback procedure

If Change 1 produces:
- A spike in `intake_routing_uncertain` rows (more than ~5% of pre-booking inbounds)
- Operator complaints about empty held drafts where they previously got
  date-deflection drafts
- Any new exception pattern in brain logs

Rollback is `git revert <commit-sha>`. Same shape as Phase 2 rollback —
this is a code change, not a runtime gate. The revert restores the date-gap
behavior on misclassified messages, which is bad but known.

## Dependencies and ordering

This phase has a soft dependency on Phase 1:

- **Step 1** (synthetic replay against LLM-first intake) can run
  independently. It's a script that takes a message text and asks the
  classifier what topic it returns. Doesn't require any flag flips or
  full dispatch infrastructure.
- **Step 2** (full dispatch replay) requires Phase 1's replay
  infrastructure to exist.
- **Step 3** (production observation) requires Phase 1's flag flip to
  have happened.

So Phase 3 Step 1 can land alongside or before Phase 1. Steps 2 and 3
follow Phase 1.

If the Step 1 results clearly point to Outcome A (LLM-first fully
resolves), we may not need to wait for Phase 1 to declare this class
verified. The fix code stays parked in this doc and only lands if Steps
2/3 show otherwise.

## Open questions for Hunter

1. **Step 1 first, or wait for Phase 1?** Step 1 is bounded enough that
   running it independently makes sense — even if Phase 1 also runs
   Case 3, having an isolated classifier-only test is useful baseline data.
2. **Confidence threshold for "class resolved."** The plan suggests >70%
   reduction in the production query as Outcome A. Adjust if too lenient
   or too strict.
3. **Change 1 vs Change 2 (Option A vs B).** Minimal vs defensive. I lean
   minimal (Option A) — fewer moving parts, easier rollback — but it's
   your call whether the audit-legibility from Option B is worth it.

## Status

This doc is **plan only**. No code change has been made. The next concrete
step is one of:

- Codex writes the Step 1 synthetic replay script and runs it against
  3-5 Spooky-class messages. Output: classification result per message,
  enough to decide Outcome A/B/C.

  OR

- Wait until Phase 1 Case 3 replay results land, then decide based on
  combined data.

Either way, no code change happens until the verification confirms one
is needed.
