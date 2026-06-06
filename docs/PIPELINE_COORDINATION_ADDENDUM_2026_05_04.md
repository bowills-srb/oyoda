# Addendum — 2026-05-04

This addendum captures resolutions, reframes, and new findings from
the audit session on 2026-05-04. Reading order: status updates to
existing sections first, then new findings.

## Status updates to existing sections

### §6.1 — Conditionally resolved (Outcome B), with reframe

**Original framing in the note:** §6.1 raised the question of whether
`missing_knowledge_topics` was being populated reliably enough that
the hold-draft heuristic could be trusted as a safety gate. §6.4 then
framed the regenerate path's omission of that gate as the core problem
("regenerate bypasses safety gate").

**What investigation found:** The framing was too strong in both
directions.

`detect_missing_knowledge` runs per-topic field-presence checks plus a
global retrieval-hit override (the `if evidence_hits: continue`
outside the per-topic loop). This is noisy in both directions: it
produces false positives when property data is thin but the inquiry
doesn't actually need that data, and false negatives when retrieval
surfaces hits that aren't relevant to the specific question being
asked. Code reading and directional production data both support this
characterization.

**Why this matters:** The gate is a heuristic, not a truth-condition.
That changes the meaning of §6.4 significantly. Regenerate's omission
of the gate is sometimes worse than the standard path (when the gate
would have correctly held a thin-grounding draft) and sometimes better
(when the gate would have spuriously held a draft that didn't need the
missing data). The asymmetry alone isn't the safety question.

**The actual safety question:** What does the model produce when
grounding is thin, and how is that gated? See Workstream 1 in
`docs/SESSION_RESUME_2026_05_05.md`. The Jackie Lee fabrication case
(§3.2) is the clearest concrete instance; see reframe below.

**Resolution status:** §6.1 closed as Outcome B with the
heuristic-noise caveat documented. §6.4 superseded by Workstream 1
framing. Re-check of aggregate hold-rate data scheduled for
2026-05-11 with methodological caveat: `parser_source =
'generic_gmail_parser'` is not a clean failure indicator because
direct-channel guest emails legitimately route through the generic
parser. Future runs need a richer filter (exclude direct-channel
sources) when interpreting hold-rate distributions.

### §3.2 — Jackie Lee case reframed

**Original framing:** Treated as evidence of regenerate-path bypassing
the safety gate. The fabricated content ("typically open year-round,
usually heated during cooler months") was attributed to the missing
gate on regenerate.

**Reframe:** This was a model-grounding failure, not a
regenerate-path bypass. The model fabricated confidently when
property data was thin. The hold-draft heuristic only sometimes masks
this class of failure; it doesn't address the underlying behavior.
Whether the gate fires or not, the model is producing
confident-sounding content from absent grounding, and that's the
failure surface that needs characterization.

This case becomes the motivating example for Workstream 1 rather than
evidence for §6.4.

### §6.3 — Resolved

Two distinct issues, both fixed in commit `ecbbfd2`:

1. **`extract_plain_text_body` re-parsing decoded bodies as RFC 2822.**
   The function was applying RFC 2822 parsing to its input regardless
   of whether the input had already been decoded by
   `_decode_gmail_payload` upstream. When the decoded body matched the
   `Word: Text\n\n` shape that RFC 2822 headers also match, the
   function stripped what it interpreted as headers, which were
   actually leading lines of the message body. This affected Vrbo
   replies and any body coincidentally matching that pattern.

2. **HTML template drift.** Vrbo's modern template uses
   `<div id="messageBody">`. The HTML extraction path didn't
   recognize this selector. Fixed in the same commit.

This is the cleanest instance in the audit so far of the
"cross-eyed child" pattern from §5; see addendum to §5 below.

### §6.6 — Resolved

`extract_property_name` strengthened to handle natural subject lines
via suffix-stripping. Subjects like "Sunrise and Sunset July
Reservation" now resolve correctly. Commit `3599502`.

### §5 — Cross-eyed-child framing validated

The framing held up under two concrete instances during this session:

1. **Read-state coordination across services.** The fix shipped to
   `oyvoda` but `oyvoda-worker` was running stale code. Each service
   was internally consistent; the seam between them was where reality
   diverged from the code's apparent behavior. Caught only via
   in-container inspection. See Workstream 6 in the resume for the
   deployment-pipeline implications.

2. **`extract_plain_text_body` category error.** The function did
   exactly what its name implied if its input were raw RFC 2822. The
   bug emerged at the seam with `_decode_gmail_payload`, where the
   input contract changed but the parsing assumption didn't. Each
   function was reasonable in isolation; the composition was the bug.

Worth carrying forward as a diagnostic lens: when something is
misbehaving and the individual components all look correct, look at
the seams between them and check whether each component's input/output
contract matches what its caller is providing.

## New findings

### Intake classification (data hygiene)

`pre_booking_inquiries` is carrying a materially mixed stream over a
30-day window. Distribution from sampling:

- ~149 categorizable non-guest rows: noreply senders, review-platform
  traffic, ops emails, non-Gmail intake
- ~142 in an "other" bucket which itself is roughly half non-guest:
  marketing, sales outreach, internal accounting, operator-domain
  emails
- Real guest traffic mixed throughout

Specific patterns observed: `marketing@breezeway.io` (vendor
marketing), `ulysses@revpartners.site` (cold sales outreach),
`lanier@beachhabitats30a.com` (operator's own domain), and various
noreply / automated system addresses.

**Two fix shapes:**

- **Short-term:** Sender blocklist for known-non-guest patterns.
  Cheap, additive, doesn't break anything. Probably catches half of
  the non-guest traffic. ~1 hour.
- **Architectural:** Classify channel + intent independently at
  intake. Every inbound email classified as guest / operator
  notification / system / marketing before routing. Multi-session
  arc.

**Operator-domain note:** The system currently treats emails from the
operator's own domain (`@beachhabitats30a.com`) as potential guest
traffic. For a multi-staff operator (the 500-unit case), each staff
member's email could end up classified as guest. Sender allowlist for
the operator's own domain is the earliest, simplest fix.

Tracked as Workstream 3 in the resume.

### Airbnb reply-channel mechanics (operator-flagged)

Question raised by the operator: Can Oyvoda actually reply to Airbnb
messages via email, or does Airbnb require login-to-platform for
replies?

**Why this is significant:** If Airbnb requires platform-login for
replies, several current assumptions break:

- The "send through Oyvoda" path (Gmail send) wouldn't reach guests on
  Airbnb threads
- Read-state semantics that depend on Oyvoda-sending don't apply to
  Airbnb threads
- The thread-state model (Option B) needs different handling for
  Airbnb than for Vrbo
- The operator may have been working around this manually

**Open questions to investigate next session:**

- Does Airbnb's `reply.airbnb.com` relay accept email replies for all
  inquiry types, or only some?
- Does it work for new pre-booking inquiries vs. only post-booking
  guest messages?
- What does `_adapt_ota_inquiry` set as the reply target for Airbnb
  rows?
- Is `_is_platform_automation_email` incorrectly classifying
  `reply.airbnb.com` addresses as automation, leaving an empty reply
  target?

This intersects with Option B (Workstream 4): if Airbnb-platform
replies don't surface in Gmail, State D detection ("operator already
replied") on Airbnb threads is harder than on Vrbo threads.

Tracked as Workstream 2 in the resume.

## Concrete commits from this session

- `3599502` — `extract_property_name` suffix-stripping for natural
  subject lines
- `1739c73` — `_mark_thread_read` after successful Gmail send
- `ecbbfd2` — `extract_plain_text_body` no longer re-parses decoded
  bodies as RFC 2822; Vrbo `<div id="messageBody">` HTML extraction;
  diagnostic logging in OTA parser failure paths
- (Pre-session) Read-state preservation on intake across `oyvoda` and
  `oyvoda-worker`

## Pointer

Forward-looking workstreams, session-opening sequence, and rollback
ordering are in `docs/SESSION_RESUME_2026_05_05.md`.
