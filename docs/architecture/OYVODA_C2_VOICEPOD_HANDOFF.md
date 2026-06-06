# C2 Hand-off — VoicePod runtime: verify-then-retire

For: Claude Code (has content-grep + live DB; this MCP session has filename-only search, so the
importer grep below could not be run here — that's step 1 for you).

## Why this exists
The audit's C2 was originally "rename the VoicePodResponse envelope (cosmetic)." Reading
app/services/knowledge/voice_pod.py showed that assumption was wrong: VoicePod is a FULL,
live-looking class — its own ConciergeRouter routing, escalation-ticket creation (writes
concierge_escalations via concierge/escalation_service.py), dining-reservation flow, Librarian
retrieval, EQ analysis, Groq→Gemini LLM generation, and a create_voice_pod() factory. So C2 is not
a rename; it's a question: is VoicePod a dormant/superseded runtime, or a SECOND live guest-response
runtime parallel to the brain orchestrator? The second case would contradict the "one decision
plane" closeout this arc just certified, so it must be answered, not assumed.

## What is already known (verified this arc, don't re-litigate)
- The live guest-ops path is: sms.py / mobile_v2.py → mobile_v2._run_voice_pod →
  messaging_brain.session_channel_adapter.run_session_channel_message →
  get_messaging_brain_orchestrator().handle_inbound_message(). Tagged session_channel_runtime="messaging_brain".
- _run_voice_pod imports ONLY `VoicePodResponse` (the dataclass) from knowledge.voice_pod — it does
  NOT import or instantiate the VoicePod class. The dataclass is reused as the response envelope.
- So on the path we traced, the VoicePod CLASS is not invoked. What's unconfirmed is whether some
  OTHER entrypoint still calls it.

## STEP 1 — Determine if VoicePod is live or dead (the decision gate)
Content-grep the repo (app/ and tests/, exclude __pycache__):
  - `VoicePod(`            (direct instantiation)
  - `create_voice_pod`     (the factory)
  - `from app.services.knowledge.voice_pod import` (what each importer actually pulls — class vs dataclass)
  - `\.respond(`           cross-check against VoicePod.respond callers
Classify every hit as: (a) imports/uses the VoicePod CLASS or create_voice_pod on a runtime path,
(b) imports only VoicePodResponse (the dataclass), or (c) test-only.

Branch:
- If the ONLY non-test live uses are VoicePodResponse (dataclass) → VoicePod class is DEAD. Go to STEP 2A.
- If anything instantiates VoicePod / calls create_voice_pod on a live (non-test) path → it is a
  SECOND RUNTIME. Go to STEP 2B. Do NOT retire it; this reopens the guest-ops "one decision plane"
  question and needs its own decision before any code change.

## STEP 2A — Retire the dormant class, keep the envelope (expected path)
Goal: remove the misleading name AND the dead second-runtime, without breaking the live envelope use.
1. Create app/services/knowledge/voice_pod_types.py (or fold into an existing messaging_brain types
   module if cleaner) containing ONLY the VoicePodResponse dataclass. Consider renaming it to a
   runtime-neutral name (e.g. SessionChannelResponse) since it's the brain session-channel envelope
   now — but keep a VoicePodResponse alias if any external/legacy import depends on the old name, to
   avoid a breaking change. Verify which name is safe via the STEP 1 grep.
2. Repoint the live importer(s) (mobile_v2._run_voice_pod, session_channel_adapter, sms.py if it
   references it) to the new types module.
3. Delete the VoicePod class + create_voice_pod factory + VoicePod-only helpers from voice_pod.py
   once nothing references them. Confirm the escalation-ticket path it used
   (concierge/escalation_service.py create_manual_escalation) has no OTHER caller that matters, or
   leave escalation_service intact (it may be used elsewhere — grep before deleting anything in it).
4. Run the full test suite + a live smoke of the guest-ops path (send a guest message through
   mobile_v2 /chat, confirm a brain-orchestrated response comes back, session_channel_runtime tag
   present). The envelope rename must not change runtime behavior.

## STEP 2B — If VoicePod IS a live second runtime (contingency)
Stop and write a short finding doc: which entrypoint calls it, for what channel/case, and whether
it's intentional (e.g. a fallback) or drift. This contradicts the certified "one decision plane"
state and is a product/architecture decision for Hunter — NOT a unilateral retire. Do not delete.

## Guardrails
- This is NOT safety-path (escalation override is already enforced + verified in the brain). Lower
  stakes than the escalation fix — but the "is there a second runtime" question is the real point.
- Don't delete anything in concierge/escalation_service.py without grepping its other callers; the
  VoicePod escalation-ticket path is one consumer, likely not the only one.
- SHIPPED = commit with SHA. Two commits suggested: (1) extract/retire VoicePod, (2) note in the
  audit C2 entry that it's resolved with the SHA.
- After STEP 1, update audit C2 STATUS regardless of branch (CLOSED-retired, or REOPENED-second-runtime).

## Done =
VoicePod class confirmed dead and retired (2A), with VoicePodResponse preserved/renamed and the live
guest-ops smoke passing — OR a finding doc raising the second-runtime case (2B). Either way, audit
C2 updated with the outcome + SHA.
