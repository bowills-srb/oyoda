# Fix 1 — Airbnb Deterministic-First

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent:** Post-Melanie parser hardening arc
**Estimated effort:** 1 hour

---

## What this fix is

Remove the special-case carveout that forces Airbnb inquiries to skip the deterministic parser and go straight to the LLM extractor. After this fix, Airbnb follows the same path as Vrbo: deterministic OTA parser first, LLM fallback only if deterministic fails to produce a usable result.

The Airbnb parser is fully implemented (`_parse_airbnb()` and `_parse_airbnb_plain_text()` in `app/services/integrations/ota_email_parsers.py`). It handles listing IDs, dates, guest names, message bodies, and reply channels. It is not "legacy" code. It was carved out of the router pipeline by a single conditional, and that conditional is what this fix removes.

---

## Why this is safe

If the Airbnb deterministic parser fails on a given email today, it returns `None`. After this fix, when it returns `None`, the router falls through to the LLM extractor — which is exactly the current behavior for *every* Airbnb email. So in the worst case, Airbnb behavior is unchanged. In the best case (and the expected case for the majority of inquiries), Airbnb emails get bound deterministically with full structured IDs, never touching the LLM.

This is a strict improvement. No Airbnb inquiry can regress as a result of this change.

---

## What this fix is not

- Not a rewrite of the Airbnb parser. The parser stays exactly as it is.
- Not a change to the LLM fallback. The LLM extractor stays exactly as it is.
- Not a change to the canonical resolver, the binding candidate logic, or any persistence path.
- Not a change to Vrbo, direct inquiries, or any non-OTA path.

This is a one-line router change plus a corresponding test update. Nothing else.

**Explicit scope guard: under no circumstances does this fix modify the Airbnb parser, the LLM extractor, the Gmail/Microsoft adapters, the canonical resolver, or any persistence code.** If a change to one of those files seems necessary to make this work, the answer is that this brief is wrong, not that the scope needs to expand. Stop and escalate.

---

## Deliverables, file by file

### 1. `app/services/integrations/email_parser_router.py`

Locate the OTA parser branch around line 394:

```python
if source_route.parser_hint == "ota" and source_route.provider != "airbnb":
    ota = parse_ota_inquiry(
        raw_html=raw_html,
        headers=headers,
        subject=subject,
        plain_text=plain_text,
    )
    if ota:
        adapted = adapt_ota_inquiry(ota)
        if adapted:
            if parser.is_non_guest_email(subject, adapted.body) and not _has_ota_inquiry_signal(ota, adapted):
                return None
            return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)
```

**Change:** Remove the `and source_route.provider != "airbnb"` clause from the conditional. The block becomes:

```python
if source_route.parser_hint == "ota":
    ota = parse_ota_inquiry(
        raw_html=raw_html,
        headers=headers,
        subject=subject,
        plain_text=plain_text,
    )
    if ota:
        adapted = adapt_ota_inquiry(ota)
        if adapted:
            if parser.is_non_guest_email(subject, adapted.body) and not _has_ota_inquiry_signal(ota, adapted):
                return None
            return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)
```

That is the entire production code change. One conditional, one clause removed.

### 2. `tests/unit/test_email_parser_router_routing.py`

Locate the test around line 134 that asserts "legacy Airbnb parser should not run" (or whatever its current name is — search for `airbnb` and `should not run` in that file).

**Change:** Invert the test. The new test should assert that Airbnb OTA inquiries *do* attempt the deterministic parser first, and only fall through to the LLM extractor when the deterministic parser returns `None` or an unusable result.

Concretely, two tests are needed in place of the old "should not run" test:

**Test A — Airbnb deterministic success path:**
- Construct a fixture Airbnb inquiry email with parseable HTML/plain text (use a real recent Airbnb email shape from the codebase or fixtures directory).
- Call `parse_structured_inbound_email(...)` with that fixture.
- Assert that `parse_ota_inquiry` was called (use a spy/mock).
- Assert that the LLM extractor was *not* called.
- Assert the returned object has `platform_listing_id` populated.

**Test B — Airbnb deterministic fallback to LLM:**
- Construct a fixture Airbnb inquiry email that the deterministic parser cannot handle (e.g., malformed HTML, missing labels). Or mock `parse_ota_inquiry` to return `None`.
- Call `parse_structured_inbound_email(...)` with that fixture.
- Assert that the LLM extractor *was* called as fallback.
- Assert the returned object is well-formed.

### 3. Validation against real fixtures

If `tests/fixtures/` or similar contains real Airbnb email samples (HTML or `.eml` files), add at least one of them as a parametrized regression test. The goal: prove the deterministic parser actually works on a real Airbnb email, not just a synthetic one.

Search the repo for existing Airbnb fixtures:

```bash
find tests -iname "*airbnb*"
find . -iname "*.eml" -path "*test*"
```

If a real fixture exists, parametrize Test A above to also run against it.

If no real Airbnb fixture exists, note this in the PR description and flag it as a follow-up. Do not block this fix on creating one — the synthetic test in Test A is sufficient for this ship.

---

## Acceptance criteria

1. The `and source_route.provider != "airbnb"` clause is removed from `email_parser_router.py`. No other production code changed.
2. The old "should not run" test is removed and replaced with the two tests described above.
3. All tests in `tests/unit/test_email_parser_router_routing.py` pass.
4. All tests in `tests/unit/test_ota_email_parsers.py` pass (regression check — Airbnb parser tests should already exist and should still pass).
5. The focused suite from the Melanie fix still passes:
   - `tests/unit/test_email_parser_router_routing.py`
   - `tests/unit/test_ota_email_parsers.py`
   - `tests/unit/test_llm_email_extractor.py`
6. PR description documents:
   - The single-line router change
   - The test inversion
   - Whether a real Airbnb fixture was added (and if not, why not)

---

## What ships after

**Fix 2 — Regression corpus.** Lock in a real-fixture regression test for every distinct inquiry shape Beach Habitats has received in the last 30 days. This is the confidence floor that prevents the next Melanie-class bug from reaching production.

---

## Notes for the executor

- Do not "improve" the Airbnb parser as part of this fix. If the deterministic parser has issues with a specific Airbnb email shape, that's a follow-up ship. This brief is strictly: remove the carveout, update the test.
- Do not change any LLM extractor logic. The fallback path is correct as it stands after the Melanie fix.
- Use the existing logging conventions in the router — no new log lines needed, the existing OTA parser logs are sufficient.

---

*End of Fix 1 brief.*
