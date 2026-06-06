# Airbnb Parser Gap Audit — 2026-05-04

Reconciliation note investigating why Airbnb messages frequently
trigger the `parse_unusable falling_back_to_generic` path observed
in oyvoda-worker logs on 2026-05-04, and classifying whether this is
expected behavior or an extraction-strategy gap.

This is a Phase 1b audit (tracker item D8). It produces a mapping
artifact, not code changes. Subsequent sessions execute against the
findings here.

## Purpose

The architecture document (`9ad2dc5`) tags "Pluggable extraction" as
partial in Section 8. The architecture commits to deterministic
extraction for stable formats with agentic fallback for novel or
heterogeneous formats. Airbnb is a major OTA whose messages flow
through Oyvoda via email-bridged forwards (Escapia → Gmail).

Worker log observation 2026-05-04 surfaced frequent
`ota_parser: parse_unusable falling_back_to_generic` log lines for
Airbnb-shaped messages. This audit investigates whether the fallback
represents:

- **Expected behavior** — the deterministic Airbnb parser is
  intentionally permissive and the generic parser correctly handles
  the fallback cases
- **Quality degradation** — fallback produces parsed output that
  downstream code compensates for, indicating an extraction gap
- **Coverage gap** — the deterministic parser doesn't cover format
  variants that exist in production traffic

The classification determines whether this is "no action needed" or
forward work in extraction strategy.

## Scope

**In scope:**
- The OTA parser surface (`app/services/integrations/ota_email_parsers.py`
  and adjacent files)
- Airbnb-specific parser logic, if it exists as a distinct surface
- The fallback condition that triggers `parse_unusable
  falling_back_to_generic`
- Empirical frequency measurement of fallback for Airbnb messages
- Quality assessment of what the generic parser produces for fallback
  cases

**Out of scope:**
- Implementing a fix
- Audit of other OTA parsers (Vrbo, Booking, etc.) — if a broader
  multi-OTA pattern surfaces, it is recorded as follow-on work, not
  absorbed into this audit
- Design of the agentic fallback strategy from architecture Section 3
- Operator-side investigation (e.g., asking Beach Habitats whether
  Airbnb inquiries have produced visible quality issues)

## Classification legend

The audit classifies the fallback observation as one of:

- **Expected by design** — fallback is deliberate, fallback path
  produces correct output, no architectural gap
- **Quality degradation** — fallback produces structured output that
  loses information or produces incorrect fields
- **Coverage gap** — deterministic parser does not cover format
  variants present in production; agentic fallback (per architecture)
  would address this
- **Mixed** — some fallback cases are expected, others are quality
  degradation or coverage gap

## Method

The audit proceeds in three rounds plus one disambiguation pass.

**Round 1 — Parser surface and fallback condition.** Grep across
`app/services/integrations/` to locate the OTA parser file structure,
identify Airbnb-specific code, find the exact `parse_unusable
falling_back_to_generic` log message, and locate the parser dispatch
logic.

**Round 2 — Fallback decision and parser body.** Targeted code reads
of `parse_ota_inquiry`, `_parse_airbnb`, and the `is_usable()` /
`summary_for_log()` methods. Establishes what specifically classifies
parser output as unusable.

**Round 3 — Empirical measurement.** SQL queries against
`pre_booking_inquiries` and `message_normalizations` to measure
parser_used distribution, message text quality, and platform-level
comparison.

**Disambiguation pass.** Single query distinguishing missing
normalization rows from present-but-parser-null rows, to determine
whether the parser provenance gap is Airbnb-specific or a system-wide
manifestation of the canonical persistence outage (Issue 3).

The audit holds scope to Airbnb. Where broader patterns surface, they
are recorded as follow-on work rather than absorbed into this note.

## Findings

### Finding 1: A dedicated Airbnb parser exists; fallback is not a coverage absence

The OTA parser surface (`app/services/integrations/ota_email_parsers.py`)
contains two dedicated Airbnb parsers:

- `_parse_airbnb(soup, subject, headers)` — HTML parser at line 666
- `_parse_airbnb_plain_text(text, subject, headers)` — plain-text parser at line 742

Plus separate Airbnb reservation-event parsers in
`ota_reservation_events.py` for review events, money-request events,
and reservation events.

The fallback to generic is not "no Airbnb parser exists." It is a
quality gate firing on the dedicated parsers' output.

### Finding 2: The fallback trigger is a message-text length gate, not exception or coverage

`ParsedOtaInquiry.is_usable()` returns True if and only if the
combined `latest_guest_turn`, `latest_operator_turn`, or `message_body`
strings (after stripping) total at least 10 characters:

```python
def is_usable(self) -> bool:
    primary_text = (
        self.latest_guest_turn
        or self.latest_operator_turn
        or self.message_body
        or ""
    ).strip()
    return len(primary_text) >= 10
```

The `parse_unusable falling_back_to_generic` log line fires after a
successful parser invocation that produced output failing this gate.

This is distinct from:
- Parser exceptions (logged as `parse crashed` or
  `plain_text_parse crashed`)
- Parser returning None (logged as `parse returned None`)

Specifically, the trigger is `_extract_airbnb_message_body(...)` and
`_extract_airbnb_plain_text_message_body(...)` failing to extract at
least 10 characters of message text from some Airbnb email shapes,
even when other structured fields (dates, listing ID, guest name)
parse successfully.

### Finding 3: Stored Airbnb inquiry quality is healthy

Empirical measurement of 13 Airbnb inquiries in
`pre_booking_inquiries` over the last 30 days shows all 13 with
`has_usable_length = true` (message_text >= 10 characters). Lengths
range from 28 to 1600 characters. Stored Airbnb message text is
substantively populated, regardless of which parser produced it.

This means the worker-log fallback observation does not map cleanly
to "bad stored Airbnb inquiry output." The downstream effect of the
fallback, if any, is not visible in `pre_booking_inquiries` content.

### Finding 4: Parser provenance is mostly absent from stored data, system-wide

The intended attribution mechanism (`message_normalizations.parser_used`)
contains parser provenance for only a small fraction of inquiries
across all platforms:

| Platform | Total inquiries | Missing normalization row | Row present, parser_used null | Row present with parser_used |
|----------|-----------------|---------------------------|-------------------------------|------------------------------|
| airbnb   | 13              | 12                        | 0                             | 1                            |
| vrbo     | 78              | 74                        | 0                             | 4                            |
| direct   | 177             | 165                       | 0                             | 12                           |

The disambiguation pass shows the gap is structural, not field-level:
where rows exist, `parser_used` is populated. The gap is missing
rows entirely.

This pattern matches the canonical persistence outage tracked as
Issue 3 (tracker A1). The audit cannot use
`message_normalizations.parser_used` to measure parser-fallback
frequency in stored data, because most joined normalization rows do
not exist.

### Finding 5: A third parser surface exists that Round 1 did not surface

The single Airbnb row with non-null `parser_used` shows
`pre_booking_transport_adapter`, not `ota_parser_airbnb` or
`generic_email_parser`. The same value appears in the Vrbo and Direct
rows that have parser provenance.

`pre_booking_transport_adapter` is a parser surface this audit did
not investigate. It is presumably a wrapper or alternate path
distinct from the OTA parser and generic parser surfaces. Whether it
is a third dedicated parser, a transport-layer adapter that wraps
one of the others, or something else is not clarified by this audit.

## Empirical measurement

Summary of measurements taken during the audit:

**Stored Airbnb inquiries (last 30 days):** 13 total. All 13 have
`message_text` length ≥ 10 characters. Lengths range from 28 to 1600
characters. Intent classifications include availability, amenities,
local_area, pricing, and general. No empty or near-empty stored
records observed.

**Parser provenance (last 30 days, all platforms):** Of 268 total
inquiries (13 airbnb + 78 vrbo + 177 direct), 251 (94%) have no
joined normalization row. 17 (6%) have rows with populated parser
provenance. Zero have rows with NULL parser provenance.

**Worker log evidence:** Frequent
`ota_parser: parse_unusable falling_back_to_generic` log lines for
Airbnb-shaped messages observed in oyvoda-worker logs on 2026-05-04.
Exact frequency not measured; observation was qualitative.

## Current state read

The audit produces a finding the original question did not anticipate.
The investigation set out to determine whether Airbnb fallback
indicates a coverage gap, quality degradation, or expected behavior.
The data does not let any of those classifications be cleanly
established, because the link between parser behavior and stored
outcomes is broken at the persistence layer, not at the parser layer.

What is established:

- The Airbnb parser exists, has both HTML and plain-text variants,
  and is invoked appropriately
- The fallback condition is a deliberate quality gate, not an absence
  of code
- Stored Airbnb inquiries land with substantive message content
- Parser provenance is not reliably captured in stored data, system-wide

What is not established:

- Whether the worker-log fallback frequency translates to
  generic-parsed records reaching `pre_booking_inquiries`
- Whether stored Airbnb inquiries with substantive content were
  produced by the dedicated Airbnb parser, the generic parser, or
  the third `pre_booking_transport_adapter` surface
- Whether downstream brain processing experiences any quality
  difference based on parser source

Closing the audit honestly requires acknowledging the second list. The
fallback observation is real; its downstream impact is not evidenced.

The largest blocker to a sharper finding is the broader
normalization-row persistence gap (Issue 3 manifestation). Until that
is closed and parser provenance is reliably retained, audits of this
shape cannot be conclusive.

## Recommended forward work

The audit produces three forward-work recommendations, in order of
scope.

### 1. Deeper Airbnb investigation deferred

Given Finding 3 (stored Airbnb quality is healthy) and the inability
to evidence downstream impact (Findings 4 and 5), deeper Airbnb-
specific investigation is on hold rather than recommended for
immediate action. The deliberate reasons for the hold are:

- no operator-visible Airbnb quality issue has been established
- the parser-provenance gap blocks measurement of parser-specific
  downstream impact
- additional parser-surface investigation today would likely produce
  the same partial finding without changing disposition

This means the audit does not recommend modifying the Airbnb parser,
the `is_usable()` gate, or the fallback dispatch logic in the current
state. These may genuinely need attention later, but immediate follow-
on work is deferred until better provenance or a concrete operator-
visible issue exists.

If a future operator surfaces a complaint about Airbnb-specific draft
quality (e.g., responses missing detail visible in the original
message), this audit's findings become reusable: the investigation
would then know to check whether `_extract_airbnb_message_body`
recovered the relevant text, and whether the fallback path produced
the affected inquiry.

### 2. Resolve normalization-row persistence (Issue 3 / tracker A1) is a prerequisite for this audit's class

The audit cannot answer its original question because parser
provenance is not retained for the majority of inquiries. Future
audits of parser behavior, extraction-strategy coverage, or
parser-specific draft quality will have the same problem until A1 is
resolved or the watch-period rule from `42ed6d5` declares it
self-resolved.

This is not new forward work — A1 already exists in the tracker. The
audit reinforces its priority among items where parser-provenance
visibility matters.

### 3. Investigate `pre_booking_transport_adapter` as a separate item

A third parser surface exists that this audit did not investigate.
Its role, scope, and relationship to the OTA parser and generic
parser surfaces are not known. A small follow-on audit (similar
shape to D8 but smaller) would map this surface and clarify whether
it is a wrapper, an adapter, or a third independent parser.

This should be added to the tracker as a new item under Workstream D,
at the same scope level as D8.

## Open questions

The audit identifies the following questions that this note cannot
resolve:

1. **What is `pre_booking_transport_adapter`?** Tracked as forward
   work item 3. Should become a new tracker item.

2. **Does the worker-log fallback frequency correlate with
   generic-parsed records reaching `pre_booking_inquiries`?**
   Resolution requires either Issue 3 fixed (so parser provenance is
   reliably stored) or a separate measurement instrument (e.g.,
   counting log occurrences and comparing to inquiry counts over the
   same window). Both are out of scope for this audit.

3. **Is the broader OTA pattern (Vrbo, Booking, etc.) similar?**
   The Vrbo row in the comparison query showed the same provenance
   gap pattern as Airbnb. Whether Vrbo's parser exhibits similar
   fallback behavior is not investigated. Out of scope per audit
   discipline; would be its own separate audit if pursued.

4. **Are the missing `message_normalizations` rows random or
   correlated with specific message shapes?** If the persistence
   failure correlates with specific platforms or formats, the
   resolution to A1 might surface platform-specific findings. The
   2026-05-03 investigation suggested possible correlation with
   `intent='availability'` and `platform='vrbo'` but did not
   conclude.

## Out of scope

This note does not:

- Make code changes to any parser
- Design the agentic fallback strategy
- Audit non-Airbnb OTA parsers
- Resolve outstanding items from prior audits
- Decide whether parser improvements are prioritized over other
  forward work in the tracker
