# Fix 2 — Inquiry Regression Corpus

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent:** Post-Melanie parser hardening arc
**Estimated effort:** 1 day
**Depends on:** Fix 1 (Airbnb deterministic-first) deployed

---

## What this fix is

A regression test corpus built from real Beach Habitats inquiries, replayed against the parser → router → canonical resolver pipeline on every deploy. The goal: any class of bug that has ever caused a binding failure in production becomes a test that fails *before* deploy, not after Lanier sees it in her inbox.

This is the confidence floor. Without it, every deploy is faith-based. With it, you have a defensible answer to "will the next inquiry bind correctly?" — namely: "every shape we've seen before, yes; new shapes, we'll see, but the test suite will catch the failure and we'll add a fixture for it."

This fix uses **zero LLM tokens**. The corpus is replayed against deterministic code paths only. LLM extractor calls in tests are mocked.

---

## What this fix is not

- Not a backfill of unbound inquiries in production data.
- Not a change to any parser, router, resolver, or persistence code.
- Not a synthetic test generator. Every fixture in the corpus is a real Beach Habitats email.
- Not a load test or performance benchmark.

This is strictly: capture real inquiries, save them as fixtures, replay them against the code, assert expected outcomes.

**Explicit scope guard: under no circumstances does this fix modify production parser, router, resolver, persistence, or database code.** It only adds test infrastructure and test data. If a fixture reveals a bug, that bug gets fixed in a separate follow-up ship.

---

## Deliverables

### 1. Fixture directory structure

Create the directory tree:

```
tests/fixtures/inquiry_corpus/
├── README.md
├── vrbo/
│   ├── 001_melanie_tarbush_4300735.eml
│   ├── 001_melanie_tarbush_4300735.expected.json
│   ├── 002_<another_real_inquiry>.eml
│   ├── 002_<another_real_inquiry>.expected.json
│   └── ...
├── airbnb/
│   ├── 001_<real_airbnb_inquiry>.eml
│   ├── 001_<real_airbnb_inquiry>.expected.json
│   └── ...
├── direct/
│   ├── 001_<real_direct_inquiry>.eml
│   ├── 001_<real_direct_inquiry>.expected.json
│   └── ...
└── reservation_events/
    ├── 001_<real_reservation>.eml
    ├── 001_<real_reservation>.expected.json
    └── ...
```

Each `.eml` file is the raw email as it arrived in production. Each `.expected.json` file is the expected output of the parser pipeline for that email.

### 2. Sourcing the corpus

Pull from production. Run a script that:

1. Queries `pre_booking_inquiries` for Beach Habitats (tenant `e07980b2-a990-4b24-91d1-c8cb71ab70e1`) over the last 30 days.
2. For each inquiry, looks up the source email payload (Gmail message ID or stored raw payload).
3. Writes the raw email to `tests/fixtures/inquiry_corpus/<platform>/<NNN>_<slug>.eml`.
4. Writes the expected parser output to `tests/fixtures/inquiry_corpus/<platform>/<NNN>_<slug>.expected.json`.

Target: **at least 20 fixtures total**, distributed across at least Vrbo, Airbnb, and direct inquiries. If fewer than 20 distinct shapes exist in the last 30 days, expand the window to 60 days. Quality matters more than count — duplicate-shape fixtures provide no additional coverage.

Categorize each fixture by shape, not just by platform. Examples of distinct Vrbo shapes:
- Modern Vrbo "is interested in your property" inquiry
- Vrbo "has replied to your message" guest reply
- Vrbo reservation event (booking confirmed)
- Vrbo inquiry with no External ID label (legacy shape)

If two fixtures share the same parser behavior end-to-end, keep one.

**Source script location:** `scripts/build_inquiry_corpus.py`. This script is run manually, not in CI. Its output is committed to the repo.

**PII redaction:** Email addresses, phone numbers, and any free-text guest content stays in fixtures (the parser needs to handle real data shapes). But sanitize obvious sensitive fields before commit:
- Replace guest email local-part with `guest_NNN` (keep relay/platform domains intact — those matter to the parser)
- Replace phone numbers with `+1-555-0100`
- Keep dates, property IDs, listing IDs, message bodies as-is

Document the redaction rules in `tests/fixtures/inquiry_corpus/README.md`.

### 3. Expected-output schema

Each `.expected.json` describes the exact parser pipeline output we want to assert against. Schema:

```json
{
  "fixture_id": "vrbo/001_melanie_tarbush_4300735",
  "description": "Vrbo inquiry with External ID 2403-268707, lower-floor bathroom question, Beach Habitats property 61CR",
  "expected_pipeline_output": {
    "parser_source": "ota_parser_vrbo",
    "platform": "vrbo",
    "lifecycle_stage": "pre_booking",
    "thread_event_type": "inquiry",
    "platform_listing_id": "4300735",
    "platform_unit_id": "unit_4874905",
    "provider_account_id": "2403",
    "provider_property_id": "268707",
    "source_property_id": "268707",
    "guest_name": "Melanie Tarbush",
    "guest_email_pattern": "@messages.homeaway.com",
    "check_in": "2026-06-09",
    "check_out": "2026-06-14",
    "guests_adults": 2,
    "message_body_contains": ["bathroom", "game room", "third floor"]
  },
  "expected_binding": {
    "should_bind": true,
    "expected_canonical_code": "61CR",
    "binding_path": "provider_property_id->canonical_property_refs"
  },
  "notes": "This is the inquiry that failed on 2026-05-19. Fixture locked in to prevent regression."
}
```

Field meanings:
- `expected_pipeline_output`: what the parser should extract. Use `_contains` suffix for partial-match strings; otherwise exact match.
- `expected_binding`: what the canonical resolver should produce. `should_bind: true` means the resolver must return a canonical property code; `should_bind: false` means the inquiry is genuinely unbindable (e.g., truly ambiguous).
- For unbindable fixtures, `expected_canonical_code` is omitted and `notes` explains why it's intentionally unbindable.

### 4. The replay test

Create `tests/integration/test_inquiry_corpus_replay.py`. Pseudocode:

```python
import json
from pathlib import Path
import pytest
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.canonical_resolver import resolve_property_for_inquiry  # use real path

CORPUS_ROOT = Path(__file__).parent.parent / "fixtures" / "inquiry_corpus"

def _discover_fixtures():
    fixtures = []
    for platform_dir in CORPUS_ROOT.iterdir():
        if not platform_dir.is_dir():
            continue
        for eml in platform_dir.glob("*.eml"):
            expected = eml.with_suffix(".expected.json")
            if expected.exists():
                fixtures.append((eml, expected))
    return fixtures

@pytest.mark.parametrize("eml_path,expected_path", _discover_fixtures(), ids=lambda p: p.stem if hasattr(p, "stem") else str(p))
async def test_inquiry_corpus_replay(eml_path, expected_path, mock_llm_extractor):
    """
    Replay a real inquiry through the parser pipeline and assert
    the parser output and canonical binding match the locked-in expectation.

    The LLM extractor is mocked to fail (return None / raise LLMEmailExtractorFallback)
    so this test only validates the deterministic path. LLM behavior is tested separately
    in test_llm_email_extractor.py.
    """
    expected = json.loads(expected_path.read_text())
    headers, subject, plain_text, raw_html = _parse_eml(eml_path)

    parsed = await parse_structured_inbound_email(
        source_message_id=expected["fixture_id"],
        subject=subject,
        plain_text=plain_text,
        raw_html=raw_html,
        headers=headers,
        parser=_test_parser(),
        adapt_llm_inquiry=_test_adapt_llm,
        adapt_reservation_event=_test_adapt_reservation,
        adapt_ota_inquiry=_test_adapt_ota,
        adapt_direct_inquiry=_test_adapt_direct,
        adapt_vendor_email=_test_adapt_vendor,
        fallback_parse=lambda: None,
        llm_extractor_factory=mock_llm_extractor,
    )

    # 1. Parser output assertions
    pipeline_expected = expected["expected_pipeline_output"]
    assert parsed is not None, f"Parser returned None for {expected['fixture_id']}"
    for field, expected_value in pipeline_expected.items():
        if field.endswith("_contains"):
            real_field = field[:-len("_contains")]
            actual = (getattr(parsed, real_field, "") or "").lower()
            for needle in expected_value:
                assert needle.lower() in actual, f"{real_field} missing {needle!r} in {expected['fixture_id']}"
        elif field.endswith("_pattern"):
            real_field = field[:-len("_pattern")]
            actual = getattr(parsed, real_field, "") or ""
            assert expected_value in actual, f"{real_field} doesn't contain pattern {expected_value!r} in {expected['fixture_id']}"
        else:
            actual = getattr(parsed, field, None)
            if hasattr(actual, "isoformat"):
                actual = actual.isoformat()
            assert actual == expected_value, f"{field}: expected {expected_value!r}, got {actual!r} in {expected['fixture_id']}"

    # 2. Binding assertions
    binding_expected = expected.get("expected_binding", {})
    if binding_expected.get("should_bind"):
        canonical = await resolve_property_for_inquiry(parsed)
        assert canonical is not None, f"Expected binding for {expected['fixture_id']}, got None"
        assert canonical.canonical_property_code == binding_expected["expected_canonical_code"], \
            f"Wrong canonical code for {expected['fixture_id']}: expected {binding_expected['expected_canonical_code']}, got {canonical.canonical_property_code}"
```

Helper functions (`_parse_eml`, `_test_parser`, etc.) go in the same file or a shared `tests/integration/_corpus_helpers.py`.

The `mock_llm_extractor` fixture (in `tests/conftest.py` or `tests/integration/conftest.py`) returns an extractor that always raises `LLMEmailExtractorFallback`, forcing the test to exercise the deterministic path only.

### 5. The canonical resolver call

The replay test asserts binding, not just parsing. This requires calling the actual canonical resolver with a real database backing. Two options:

**Option A (preferred): live test database.**
Spin up a Postgres test instance with the production `canonical_property_refs` table loaded from the Escapia CSV. The CI workflow does this in a Docker container. The replay test connects to it.

**Option B (acceptable): mock the resolver.**
Mock the resolver to look up against an in-memory map built from the Escapia CSV. Faster, simpler, but doesn't catch bugs in the resolver itself.

Pick Option A if the CI infrastructure already supports a test Postgres (check `.github/workflows/` and `docker-compose.test.yml` or equivalent). Otherwise start with Option B and flag Option A as a follow-up.

### 6. CI integration

Add the corpus replay test to the CI workflow that runs on every PR and every deploy to Railway. If CI is currently `pytest tests/unit/`, expand to `pytest tests/unit/ tests/integration/test_inquiry_corpus_replay.py`.

If the full corpus is slow (>30 seconds), add a `@pytest.mark.corpus` decorator and split CI into a fast suite (unit) and a slow suite (corpus). Both must pass before deploy.

### 7. README

`tests/fixtures/inquiry_corpus/README.md` must document:

- What the corpus is and why it exists
- How to add a new fixture (the workflow when a new bug is found)
- The redaction rules
- The fixture naming convention
- How to regenerate `.expected.json` files when intentional parser changes happen

The new-fixture workflow is the most important part. When a Melanie-class bug is found in the future:

1. Save the offending email as `.eml` in the appropriate platform directory.
2. Write the `.expected.json` describing what the parser *should* produce.
3. Run the corpus test — it fails for the new fixture.
4. Fix the parser/router/resolver until the test passes.
5. Commit the fix and the fixture together.

This is the loop. Document it in the README so it survives context resets.

---

## Acceptance criteria

1. `tests/fixtures/inquiry_corpus/` directory exists with at least 20 real Beach Habitats fixtures across at least Vrbo, Airbnb, and direct categories.
2. `scripts/build_inquiry_corpus.py` exists and can regenerate fixtures from production (committed to repo, runnable locally).
3. Each `.eml` has a matching `.expected.json` following the schema in this brief.
4. `tests/integration/test_inquiry_corpus_replay.py` exists and:
   - Discovers all fixtures automatically
   - Parametrizes the replay test over all fixtures
   - Asserts parser output matches `.expected.json` exactly
   - Asserts canonical binding matches `expected_binding` (via real resolver or mock per Option A/B above)
5. The Melanie fixture (`vrbo/001_melanie_tarbush_4300735.eml`) exists and the test passes after Fix 1 deploys. This is the canary fixture — if it ever fails again, we know binding regressed for the exact case that motivated this work.
6. All corpus tests pass on CI.
7. `tests/fixtures/inquiry_corpus/README.md` documents the new-fixture workflow.
8. PII redaction has been applied per the rules in this brief.
9. PR description lists every fixture added and what shape it covers.

---

## What ships after

**Fix 3 — Daily binding report.** A cron job that emails Hunter every morning with yesterday's binding rate, the unbound inquiries (with surfaced identifiers), and the resolution path for each bound inquiry. This is the operational feedback loop so the next Melanie is caught by the cron, not by Lanier.

After Fix 3 ships, the focus returns to the UI redesign — Ship A and the proposal in `COMMAND_MODULE_PROPOSAL.md`.

---

## Notes for the executor

- This fix touches *no* production code. If you find yourself editing files outside `tests/`, `scripts/build_inquiry_corpus.py`, or CI config, you've left scope.
- The corpus is meant to grow. The 20-fixture target is a minimum, not a ceiling. Every future Melanie-class bug should result in a new fixture committed alongside its fix.
- Treat the `.expected.json` files as the source of truth. If the parser changes intentionally (e.g., extracting a new field), update the expectations in the same commit as the parser change.
- The LLM is mocked to fail in these tests on purpose. The deterministic path is what we're validating. LLM behavior has its own test file.

---

*End of Fix 2 brief.*
