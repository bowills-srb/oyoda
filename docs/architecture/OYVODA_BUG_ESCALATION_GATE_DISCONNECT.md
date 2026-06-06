# Bug Brief — Autonomy gate escalation override is disconnected (safety-path)

Status: VERIFIED, unresolved. Severity: HIGH (safety path — affects whether the AI auto-sends on
escalated messages). Not a typo; a structural producer/consumer + signal-wiring gap. Captured for a
scoped fix, NOT an inline change (touches ResponsePolicyAgent + autonomy_gate + risk-flag contract +
escalation-table decision). The autonomy_gate.py docstring (note 4) carries an inline tripwire
pointing here.

## What "escalations override everything" is supposed to mean
autonomy_gate.py design note 2: if the inbound message triggered an escalation, the draft is HELD
regardless of confidence/autonomy mode. This is the highest-priority safety override. As built, the
mechanisms that are supposed to enforce it are disconnected. Three findings:

## Finding 1 — the table lookup reads a table nothing writes (producer/consumer drift)
- `autonomy_gate.check_blocking_escalation` (~line 154) READS `conversation_escalations`.
- Live escalation WRITER is `concierge/escalation_service.py` (~line 249) → writes
  `concierge_escalations`. Migration 027 says `concierge_escalations` "remains in use for old flows."
- No in-tree producer writes `conversation_escalations`. Both tables exist; both currently 0 rows
  (so no test/data surfaces it). → The table lookup is INERT for current escalation flows.

## Finding 2 — the brain's escalation DECISION is a risk flag the gate never reads
- `messaging_brain/agents/escalation_agent.py` produces `recommended_action=ESCALATE` +
  risk_flags `escalation_emergency` / `escalation_complaint`. Its docstring is explicit: the agent
  NEVER writes a DB row (Rule 4: agents decide, modules/services do work). So in the brain pathway an
  escalation is NOT a row in either table at decision time — it's a flag on the AgentDecision.
- Same docstring, "Policy-gate interaction (current limitation)": ResponsePolicyAgent / autonomy_gate
  does NOT look at specialists' recommended_action. So the `escalation_emergency` HARD-STOP flag is
  NOT consumed by the gate. The agent docstring itself names the needed fix: "A future policy
  refinement should make recommended_action=ESCALATE from any specialist a hard force on the gate's
  final_action."

## Finding 3 — what actually holds the line today (weaker than documented)
- The practical safety net is NOT the documented override. It's that emergency/complaint messages get
  `urgency=EMERGENCY` / `requires_human_review=True`, and the gate's confidence/review path routes
  those to REVIEW. That is an INDIRECT guarantee, not the "escalation hard-blocks regardless"
  guarantee note 2 claims. Whether it reliably catches EVERY escalation case (esp. auto-mode
  properties at high confidence) must be verified separately — it is not equivalent to a hard stop.

## Severity / blast radius
The failure mode is: an escalated message on an auto-mode property could pass the gate to AUTO_SEND
because (1) the table lookup finds nothing and (2) the risk flag is unread — leaving only the
indirect urgency path. Invisible today (0 escalation rows), bites when a real escalation coincides
with auto mode. This is the same silent-mismatch pattern as the Piece A / learning-capture bugs, but
on a safety path, so higher stakes.

## The fix is TWO-PART (neither A nor B alone is sufficient)
PART 1 — make the brain escalation signal authoritative on the gate (the brain-native fix):
  - Wire `recommended_action=ESCALATE` and the `escalation_emergency`/`escalation_complaint` risk
    flags from any specialist to HARD-FORCE `final_action` in ResponsePolicyAgent / autonomy_gate.
    `escalation_emergency` must be an absolute hard-stop (never auto-send, any confidence/mode) — the
    agent docstring already specifies this intent. This is the correct brain-pathway mechanism:
    escalation lives in the AgentDecision, so the gate should honor THAT, not a table.
PART 2 — resolve the table lookup's purpose:
  - Decide what `check_blocking_escalation` is for. If out-of-band escalations created by
    `escalation_service.py` (concierge_escalations) still need to block drafts, point the read at
    `concierge_escalations` (the live writer). If the brain risk-flag path (Part 1) fully covers
    escalation blocking, the `conversation_escalations` lookup may be removable rather than re-pointed.
  - Do NOT simply re-point to `conversation_escalations` (nothing writes it) — that leaves it inert.

## Decision needed before patching
Which is the canonical escalation signal going forward: the brain AgentDecision risk flag (Part 1,
preferred per "all on the brain"), or a persisted escalation row? Recommendation: brain risk flag is
authoritative for the brain pathway; the table lookup is a legacy/out-of-band mechanism that should
either read the live table (concierge_escalations) or be retired. Confirm by checking whether any
non-brain flow still needs the draft held based on a persisted escalation row.

## Verification (once patched)
- Emergency-classified message on an AUTO-mode, high-confidence property → gate returns REVIEW/blocked
  (NOT auto_send), driven by the escalation risk flag (Part 1).
- A persisted escalation (whichever table is canonical) on a message → draft held (Part 2).
- Regression: non-escalation high-confidence auto-mode draft still auto-sends.
- Because both tables are empty, verification must CREATE the scenario (classified emergency +
  auto-mode property), not look for existing data.

## Scope guards
- Safety path — do not weaken existing REVIEW routing while wiring the hard-stop.
- `escalation_emergency` is an absolute hard-stop; never gate it behind confidence or autonomy mode.
- Keep it brain-native: the gate should consume the brain's escalation decision, not reach into a
  legacy concierge service. If the table lookup stays, it reads the live table, no new bridge.
