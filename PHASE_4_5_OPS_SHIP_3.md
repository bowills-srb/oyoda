# Ship 3 — Composer Overhaul + CLARIFY Action

## Goal

Two pieces shipping together because they're entwined: tighten the composer prompt to fix the corporate-tone and hallucination failures we observed (Taylor, Matthew, Carri), and add the CLARIFY action that lets the AI ask clarifying questions instead of dodging ambiguous inquiries.

## Why these ship together

The composer's system prompt and the CLARIFY mode are read by the same model in the same call. Building CLARIFY without overhauling the prompt produces clarification questions in the same corporate voice ("Our concierge team would love to gather more details before we can assist..."). Overhauling the prompt without CLARIFY just makes the dodges sound friendlier without resolving them. Both pieces need to ship together to actually move draft quality.

## What we know from the 5 drafts we've read

**Taylor Molina** — guest mentioned eloping, asked to host a gathering. Draft was corporate, dodged the question, invented "our concierge team," bolted on cancellation disclaimer. The fix is CLARIFY: ask group size and event type, share the relevant property fact (sleeps N), get to a real answer in turn 2.

**Carri Bevil** — asked about beach chairs, towels, coffee maker, house guide link. Draft was "I want to confirm the exact details before I answer." Right hedging stance, too thin. The fix is partial answers: answer the parts we know (coffee maker from property data) and ask only about the parts we don't.

**Matthew Morrison** — early-checkin question. Draft said no early access, then said "we will confirm with our team," then told the guest to text "me" at the guest's own phone number. The fix is grounding: never echo back the guest's own phone as "me," and never invent organizational entities.

**Monica Duvall** — parking question, no property binding. Generic "I'm pulling together details." Not a fair sample because binding failed (Ship 6 problem).

**Christina Moser** — predates the brain. Not a fair quality sample.

The composer overhaul targets Taylor (CLARIFY), Carri (partial-answer mode), Matthew (grounding rules). Monica is a Ship 6 concern. Christina is historical.

## Required reading

- `OPERATOR_READINESS_ARC.md`
- `app/services/messaging_brain/agents/llm_composer_agent.py` — the current composer system prompt and user-message assembly
- `app/services/messaging_brain/agents/booking_inquiry_agent.py` and the other specialist agents (`access_agent.py`, `house_rules_agent.py`, `maintenance_agent.py`) — where CLARIFY emission lives
- `app/services/orchestration/messaging_brain_contracts.py` — where the `RecommendedAction` enum and `AgentDecision` shape live
- `app/services/messaging_brain/agents/response_policy_agent.py` — where the policy treatment of CLARIFY needs to land

## Tasks

### Part A — Composer prompt overhaul

#### A1. Universal voice/craft layer

Add to the top of the composer system prompt, before existing discipline rules:

```
VOICE PRINCIPLES (apply always):
- Write the way a real innkeeper writes — warm but direct, never corporate.
- Match the guest's energy. Casual gets casual ("happy to host you, just need a few details"). Formal gets formal ("delighted to host your celebration").
- Never use these phrases: "our team," "our concierge team," "our staff" (unless the operator's persona explicitly says otherwise), "we'd be happy to discuss the possibility of," "please be aware that our standard cancellation policy applies," "reach out to," "I'd be happy to assist."
- Never add disclaimers about topics the guest didn't raise (cancellation, T&Cs, fees, policies they didn't ask about).
- Never restate the guest's own observations back to them ("Yes, our property is beautiful as you noted").
- Never use the guest's own phone number when referring to "me" — phone numbers in the guest's message belong to the guest.
- If you don't have a fact, ask for it or say you'll confirm — don't fabricate.
- Sign off naturally with the operator's name or "the team" only if the operator's persona says so. Otherwise no sign-off — just end the message naturally.
```

#### A2. Operator-specific voice/persona layer

Add a new section in the system prompt that reads from the new `operator_ai_guidance` fields (added in Ship 4 — for Ship 3, the read still works against currently-empty fields, the prompt just notes when persona is absent):

```
OPERATOR PERSONA:
{operator_persona_text if not empty else "No specific persona declared — apply universal voice principles."}

OPERATOR EXAMPLE REPLIES (match this voice):
{operator_example_replies if not empty else "No example replies provided yet."}
```

The composer reads `operator_ai_guidance.persona_text` and `operator_ai_guidance.example_replies` (new fields, added schema in this ship). When empty, the prompt notes it and falls back to universal defaults.

#### A3. Tightened negative constraints

Replace the existing "what not to do" list with the specific banned phrases observed in real failures. Codex extracts the exact phrasings from the 5 drafts we've read (and any new drafts from Ship 1 post-deploy) and bakes them into the negative-example list.

#### A4. Sentence cap raised, temperature raised

In the composer agent code:
- Change sentence guidance from "2-3 sentences" to "2-5 sentences as needed — be complete, not telegraphic"
- 700-char cap stays
- Temperature 0.3 → 0.5

### Part B — CLARIFY action

#### B1. Add CLARIFY to RecommendedAction enum

In `app/services/orchestration/messaging_brain_contracts.py`:

```python
class RecommendedAction(str, Enum):
    AUTO_SEND = "auto_send"
    DRAFT_ONLY = "draft_only"
    ESCALATE = "escalate"
    CLARIFY = "clarify"   # NEW: ask the guest for missing context
```

#### B2. Add `clarification_questions` field to AgentDecision

Same file:

```python
@dataclass
class AgentDecision:
    # existing fields...
    clarification_questions: List[str] = field(default_factory=list)
```

When a specialist recommends CLARIFY, it populates this list with the 1-3 specific questions it needs answered.

#### B3. Specialist agents emit CLARIFY when appropriate

In each specialist agent (BookingInquiryAgent, AccessAgent, HouseRulesAgent, MaintenanceAgent), add logic that distinguishes *askable* missing info from *unknowable* missing info:

**Askable** (guest can answer):
- Group size
- Dates / check-in or check-out specifics
- Event type ("dinner with family" vs "reception")
- Number of pets, type of pet
- Special requirements
- Whether they've stayed before
- Their preference between two options the operator offers

**Not askable** (guest doesn't know):
- Whether the pool is heated
- Specific property amenities
- Operator policy on a specific scenario
- Pricing details

When the specialist's missing_info has at least one askable item, it emits `RecommendedAction.CLARIFY` with `clarification_questions` populated. Otherwise it falls back to DRAFT_ONLY (existing behavior — hedge with confirmation).

Each specialist defines its own logic for which missing fields are askable, based on the inquiry types it handles. Document this in each agent's docstring.

#### B4. Composer CLARIFY mode

When a specialist recommends CLARIFY, the composer's user-message assembly includes the clarification questions and the system prompt adds a CLARIFY-mode instruction block:

```
THIS IS A CLARIFICATION REPLY:
The specialist agent has identified that you don't have enough context from the guest to give a substantive answer. Your job is to ask the specific clarifying questions below in a warm, natural way.

Questions to ask:
{clarification_questions, formatted as bullets}

Structure your reply as:
1. Acknowledge the guest's request positively (one sentence)
2. Share one relevant fact from property data if helpful (one sentence, optional)
3. Ask the clarifying questions naturally (one or two sentences)

Do not say "we'll get back to you" or "we need to check on this" — just ask. Do not hedge. Do not commit to anything yet — you're gathering information.
```

#### B5. Policy agent treatment of CLARIFY

In `response_policy_agent.py`, add handling for CLARIFY actions:

- Clarification questions don't make commitments, don't share confidential info, don't promise anything. They're inherently safer than substantive drafts.
- For properties in AUTO mode with CLARIFY action: auto-send at a lower confidence threshold than substantive drafts (e.g. 0.6 instead of the standard 0.75-0.9). Codex picks a sensible default.
- For properties in REQUIRED mode: CLARIFY drafts still go to operator review (REQUIRED is REQUIRED), but they're flagged as "clarification question" type in the queue UI so Lanier can quickly identify and approve them.

#### B6. Audit captures CLARIFY turn

When a CLARIFY response goes out, the audit row in `parser_notes` should capture:
- `type: "clarify_emission"`
- `clarification_questions: [...]`
- `auto_sent: true | false`

This lets us measure later: what fraction of inquiries triggered CLARIFY, what fraction of clarifications got a useful guest response, how much CLARIFY reduces operator review burden.

#### B7. Turn-2 awareness

When the next inbound message arrives from a guest that just received a CLARIFY response, the brain should recognize it as turn 2 of a clarification exchange. The context bundle to the composer should include:
- The original guest message (turn 1)
- The CLARIFY response (turn 1 outbound)
- The guest's turn 2 reply (the new inbound)

So the composer has full context to produce the substantive answer. The thread context lookup probably already supports this — Codex verifies and adds it if needed.

### Part C — Schema changes

Add fields to `operator_ai_guidance` table for the operator-specific voice layer:

```sql
ALTER TABLE operator_ai_guidance
    ADD COLUMN IF NOT EXISTS persona_text TEXT,
    ADD COLUMN IF NOT EXISTS example_replies JSONB DEFAULT '[]'::jsonb;
```

- `persona_text` — free-form description of how the operator wants the AI to sound
- `example_replies` — JSONB array of operator-curated example reply pairs (`{"inquiry_type": "amenities", "guest_message": "...", "reply": "..."}`)

These fields are empty after this ship. Ship 4 builds the UI to populate them. The composer reads them gracefully when empty (falls back to universal defaults).

## Tests

- Composer prompt assembly: with empty persona, the prompt notes "no specific persona" and applies universal rules
- Composer prompt assembly: with populated persona, the operator's voice description appears in the prompt
- BookingInquiryAgent: an inquiry like Taylor's (event hosting, missing group size) emits CLARIFY with appropriate questions
- BookingInquiryAgent: an inquiry like a basic check-in question (clear, no missing askable info) emits DRAFT_ONLY as before
- Composer in CLARIFY mode: produces a reply that acknowledges, shares one fact if available, and asks the specific questions — does not hedge
- Policy agent: CLARIFY response from AUTO property gets auto-sent at lower confidence threshold
- Policy agent: CLARIFY response from REQUIRED property goes to review queue with "clarification question" flag
- End-to-end: Taylor-like inquiry → CLARIFY response → simulated guest turn-2 reply with answers → substantive turn-3 draft

## Ship criteria

- Composer system prompt overhauled per A1-A4
- CLARIFY action wired through enum, agents, composer, policy per B1-B7
- Schema fields added to `operator_ai_guidance` per Part C
- Tests pass
- Taylor's case regression: a guest message similar to Taylor's produces a CLARIFY response, not a dodge
- Matthew's case regression: a guest message that includes the guest's own phone number doesn't get echoed back as "me"
- 10 fresh production drafts (post-Ship-1) read manually — composer fixes visible
- `OPERATOR_READINESS_ARC.md` status updated: Ship 3 → DEPLOYED → VERIFIED

## What this ship does NOT do

- Does NOT populate the persona/example fields (Ship 4 — UI to populate them)
- Does NOT add UI for the queue review workflow (Ship 5)
- Does NOT fix the 43-row property-binding gap (Ship 6)

## Codex commit-message format

```
phase 4.5 ops ship 3: composer overhaul + CLARIFY action

composer prompt:
  - universal voice/craft layer at top
  - operator-specific persona section (reads new operator_ai_guidance fields)
  - tightened negative constraints with observed-failure phrases banned
  - temperature 0.3 → 0.5
  - sentence cap 2-3 → 2-5

CLARIFY action:
  - new RecommendedAction.CLARIFY enum value
  - clarification_questions field on AgentDecision
  - specialist agents emit CLARIFY when missing info is askable
  - composer CLARIFY mode produces ask-don't-dodge replies
  - policy agent: CLARIFY auto-sends at lower confidence threshold
  - audit captures clarify_emission with questions and auto_sent flag

schema:
  - operator_ai_guidance.persona_text (empty until ship 4)
  - operator_ai_guidance.example_replies (empty until ship 4)

verification:
  - taylor regression: similar inquiry produces CLARIFY, not dodge
  - matthew regression: guest's phone not echoed as "me"
  - 10 fresh production drafts read: corporate phrasings absent, ask-don't-dodge visible
```
