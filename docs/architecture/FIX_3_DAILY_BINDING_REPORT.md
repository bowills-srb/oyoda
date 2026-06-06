# Fix 3 — Daily Binding Report

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent:** Post-Melanie parser hardening arc
**Estimated effort:** Half a day
**Depends on:** Nothing. Can ship in parallel with Fix 1 and Fix 2.

---

## What this fix is

A daily cron job that queries the previous 24 hours of inquiries, computes binding stats, and emails Hunter a summary every morning. The point is to close the operational feedback loop: instead of discovering binding failures by scrolling Lanier's inbox, Hunter sees them in a daily report before they pile up.

This is **operational instrumentation**, not a feature. The output is read by one person (Hunter) and informs whether more parser hardening is needed. Once Beach Habitats is stable and the binding rate is consistently above 95%, the report becomes a weekly digest instead of daily. For now, it ships daily.

This fix uses **zero LLM tokens**. Everything is SQL queries against existing tables, formatted into a text/HTML email body. No model calls.

---

## What this fix is not

- Not a dashboard. The output is an email, not a web surface. Dashboards land in the frontend redesign (Ship A and onward).
- Not a real-time alerting system. Daily granularity, not push notifications. Real-time alerting is a separate ship.
- Not an analytics product. Just enough to answer: "did anything fail to bind yesterday, and if so, what was the signal that should have resolved it?"
- Not a multi-tenant report. Single-tenant for Beach Habitats. Multi-tenant expansion is a follow-up.

**Explicit scope guard: under no circumstances does this fix modify the parser, router, resolver, or any inbound message handling code.** It only reads from existing tables and sends one email per day. If a query reveals a bug, that bug gets fixed in a separate ship.

---

## Deliverables

### 1. The report query

Create `app/services/reports/daily_binding_report.py`. The module exposes one async function:

```python
async def build_daily_binding_report(
    session: AsyncSession,
    tenant_id: str,
    window_hours: int = 24,
) -> DailyBindingReport:
    ...
```

The function queries the inquiry/normalization tables and returns a structured report.

**What to query (anchored to schemas you already have):**

For every `pre_booking_inquiries` row created in the last `window_hours` for the given `tenant_id` (Beach Habitats: `e07980b2-a990-4b24-91d1-c8cb71ab70e1`), join to `message_normalizations` on the matching `message_id` and produce per-inquiry:

- `inquiry_id` (the `pre_booking_inquiries.id` or `draft_id`)
- `received_at` (`pre_booking_inquiries.created_at` or equivalent timestamp)
- `platform` (e.g. `vrbo`, `airbnb`, `direct`)
- `parser_used` (from `pre_booking_inquiries.parser_used` if present, else `message_normalizations.parser_used`)
- `guest_name` (from `pre_booking_inquiries.guest_name`)
- `property_external_id` (from `pre_booking_inquiries`)
- `selected_property_code` (from `message_normalizations`)
- `selected_property_match_type` (from `message_normalizations`)
- `property_binding_candidates` (from `message_normalizations`, parsed if stored as JSON)
- `parser_notes` (from `message_normalizations`, parsed if stored as JSON)
- `surfaced_identifiers` — every property ID surfaced anywhere in the row (subject/body parsed mentions, external_id, listing_id, etc.)

Group results into three buckets:

- **Bound**: `selected_property_code` is non-empty.
- **Unbound but resolvable**: `selected_property_code` is empty, but at least one surfaced identifier *exists in `canonical_property_refs`*. This is the high-priority bucket — these are the Melanie-class failures.
- **Unbound and not resolvable**: `selected_property_code` is empty and no surfaced identifier maps to anything in `canonical_property_refs`. These are genuine unknowns (new property, garbled email, spam slipping through layer 1).

The "unbound but resolvable" bucket is the alarm bell. Any row in it indicates that the parser captured a usable identifier but the binding pipeline dropped it.

### 2. The report data structure

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class InquiryReportRow:
    inquiry_id: str
    received_at: datetime
    platform: str
    parser_used: str
    guest_name: Optional[str]
    property_external_id: Optional[str]
    selected_property_code: Optional[str]
    selected_property_match_type: Optional[str]
    surfaced_identifiers: list[str]
    resolvable_canonical_code: Optional[str]  # set if unbound-but-resolvable

@dataclass
class DailyBindingReport:
    tenant_id: str
    window_start: datetime
    window_end: datetime
    total_inquiries: int
    bound: list[InquiryReportRow]
    unbound_resolvable: list[InquiryReportRow]
    unbound_unknown: list[InquiryReportRow]

    @property
    def binding_rate(self) -> float:
        if self.total_inquiries == 0:
            return 1.0
        return len(self.bound) / self.total_inquiries

    @property
    def regression_count(self) -> int:
        return len(self.unbound_resolvable)
```

### 3. The email formatter

Create `app/services/reports/daily_binding_email.py`. One function:

```python
def render_daily_binding_email(report: DailyBindingReport) -> tuple[str, str, str]:
    """
    Returns (subject, plain_text_body, html_body) for the daily report email.
    """
```

**Subject line format:**

- If `regression_count > 0`: `[Oyvoda] Binding report — {regression_count} unbound but resolvable yesterday`
- Else if `binding_rate >= 0.95`: `[Oyvoda] Binding report — {total} inquiries, {pct}% bound`
- Else: `[Oyvoda] Binding report — {pct}% bound, attention needed`

The subject line is the entire signal for days when nothing is broken. Hunter should be able to glance at the subject and know whether to open the email.

**Plain-text body structure:**

```
Oyvoda — Daily Binding Report
Tenant: Beach Habitats 30A
Window: 2026-05-19 00:00 UTC → 2026-05-20 00:00 UTC

═══════════════════════════════════════════════════════════
SUMMARY
═══════════════════════════════════════════════════════════
Total inquiries:           43
Bound:                     40  (93.0%)
Unbound but resolvable:     2  ← ATTENTION
Unbound and unknown:        1

═══════════════════════════════════════════════════════════
UNBOUND BUT RESOLVABLE  (these should have bound)
═══════════════════════════════════════════════════════════

[1] INQ-39803FCE  ·  Vrbo  ·  Melanie Tarbush  ·  09:14 AM
    Surfaced identifiers: #4300735, 2403-268707, 268707
    Resolvable to:        61CR (via provider_property_id)
    Parser used:          prebooking_request
    Why it didn't bind:   property_binding_candidates was empty
                          at canonical persist time

[2] INQ-XXX...
    ...

═══════════════════════════════════════════════════════════
UNBOUND AND UNKNOWN
═══════════════════════════════════════════════════════════

[1] INQ-XXX  ·  Direct  ·  10:42 AM
    Surfaced identifiers: (none)
    Why it didn't bind:   no identifiers in inquiry; likely
                          new property or spam-leak

═══════════════════════════════════════════════════════════
BOUND  (collapsed — open the report to expand)
═══════════════════════════════════════════════════════════

40 inquiries bound successfully.
By platform:  Vrbo: 28  ·  Airbnb: 8  ·  Direct: 4
By match type: external_id: 21  ·  listing_id: 14  ·  unit_code: 5

— Oyvoda
```

**HTML body:** Same content, lightly styled. Don't over-engineer it. Tables with subtle borders, monospace font for IDs, the "unbound but resolvable" section in red, and that's it. This is an internal ops email, not a customer-facing product surface.

### 4. The dispatch function

Create `app/services/reports/operator_notification.py`. Reuses the SMTP/transport already configured for outbound email (check `app/services/integrations/email_dispatch.py` for the existing transport).

```python
async def send_operator_notification(
    *,
    to_address: str,
    subject: str,
    plain_text: str,
    html: str,
) -> bool:
    ...
```

This is a thin wrapper around the existing email transport. Do not create a new SMTP client. Reuse what's already there. If `email_dispatch.py` doesn't expose a reusable function, refactor minimally — extract one helper, don't rewrite the module.

### 5. The cron entry point

Create `scripts/run_daily_binding_report.py`. A standalone script that:

1. Connects to the database.
2. Calls `build_daily_binding_report(...)` for `tenant_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1`.
3. Renders the email via `render_daily_binding_email(...)`.
4. Sends it via `send_operator_notification(...)`.
5. Logs success/failure.

The script reads recipient address from env var `OPERATOR_REPORT_RECIPIENT` (default: Hunter's email — set in Railway env).

The script reads tenant ID from env var `OPERATOR_REPORT_TENANT_ID` so it's not hardcoded. Default in env: `e07980b2-a990-4b24-91d1-c8cb71ab70e1`.

### 6. Scheduling

The script runs once daily. Use whatever scheduling Railway/the deploy environment already supports.

If Railway supports cron natively, add a cron service to `railway.toml` or the equivalent config:

```
[cron.daily_binding_report]
schedule = "0 13 * * *"   # 13:00 UTC = 08:00 Central = morning for Hunter
command = "python scripts/run_daily_binding_report.py"
```

If Railway doesn't support cron, fall back to GitHub Actions cron (`.github/workflows/daily_binding_report.yml`) that hits a Railway endpoint, or to APScheduler embedded in the FastAPI app. Pick whichever is simplest and already used elsewhere in the codebase. Check before inventing a new pattern.

### 7. Tests

Create `tests/unit/test_daily_binding_report.py`. Cover:

**Test 1 — empty window.** No inquiries in the window. Report has `total_inquiries == 0`, `binding_rate == 1.0`, all three buckets empty. Subject reads "0 inquiries, 100% bound" or similar.

**Test 2 — all bound.** Seed fixtures for 5 bound inquiries. Report shows 5 in `bound`, empty in both unbound buckets. Subject reads "5 inquiries, 100% bound".

**Test 3 — Melanie-class regression.** Seed a fixture with empty `selected_property_code` but a surfaced `property_id` that maps to `61CR` in `canonical_property_refs`. The report puts this inquiry in `unbound_resolvable`. Subject reads "1 unbound but resolvable yesterday" with the regression_count in it.

**Test 4 — genuinely unknown.** Seed a fixture with no surfaced identifiers. The report puts this in `unbound_unknown`. Doesn't trigger the regression-count subject.

**Test 5 — email formatter.** Pass a constructed report through `render_daily_binding_email` and assert subject/body shape. String matching is fine.

No need to test the dispatch function — that's the existing email transport, already tested elsewhere.

---

## Acceptance criteria

1. `app/services/reports/daily_binding_report.py` exists and exposes `build_daily_binding_report(session, tenant_id, window_hours=24)`.
2. `app/services/reports/daily_binding_email.py` exists and exposes `render_daily_binding_email(report)`.
3. `app/services/reports/operator_notification.py` exists and exposes `send_operator_notification(...)`, reusing the existing email transport.
4. `scripts/run_daily_binding_report.py` exists and runs end-to-end against a configured database and recipient.
5. The script is scheduled to run once daily (Railway cron, GitHub Actions cron, or APScheduler — whichever is consistent with the rest of the codebase).
6. `tests/unit/test_daily_binding_report.py` exists and all five tests pass.
7. The recipient address is configurable via env var `OPERATOR_REPORT_RECIPIENT`.
8. The tenant ID is configurable via env var `OPERATOR_REPORT_TENANT_ID`.
9. The first scheduled run after deploy successfully delivers an email to Hunter. Check inbox to confirm.
10. PR description documents: the query shape, the bucketing rules, the email format, and where the cron is configured.

---

## What ships after

After Fix 3 lands, the focus returns to the UI redesign:

- Commit and hand off **Ship A** (`SHIP_A_FOUNDATIONS.md`) to Codex.
- After Ship A deploys, scope **Ship B** (shell + nav restructure).
- Continue the ship sequence in `COMMAND_MODULE_PROPOSAL.md`.

The parser hardening arc is done. The product has:
- Deterministic-first for all major OTAs (Fix 1)
- A regression corpus that catches Melanie-class bugs before deploy (Fix 2)
- A daily operational feedback loop so binding failures surface within 24 hours, not whenever someone happens to look (Fix 3)

That's the confidence floor. After that, every hour goes to the UI.

---

## Notes for the executor

- Reuse the existing email transport. Do not introduce a new SMTP client or email library.
- The report is plain SQL against existing tables. No new tables, no new migrations.
- The cron schedule (`0 13 * * *`) is a suggestion — match it to whatever time Hunter actually wants the report delivered. Check before deploying.
- The "Why it didn't bind" line in the report is generated from heuristics on `parser_notes` and `property_binding_candidates`. Keep the heuristics simple — if the explanation isn't obvious from the data, write "see parser_notes" and let Hunter dig.
- If the email transport is misconfigured (no SMTP creds in env), the script should log loudly and exit nonzero, not crash silently. Hunter needs to know if the report didn't send.

---

*End of Fix 3 brief.*
