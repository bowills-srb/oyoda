# Inquiry Regression Corpus

This corpus is the real-fixture companion to the synthetic Brain-era regression harness.

## What it is

- Real Beach Habitats pre-booking inquiry shapes exported from production
- Committed fixtures used to replay the parser/router path against preserved inbound envelopes
- A way to catch parser and routing regressions before deploy

## Fidelity

Production does **not** currently preserve full raw RFC822 email for these inquiries in a dedicated payload table.

Ship Q therefore uses the highest-fidelity inbound envelope the database does preserve:

- `message_normalizations.raw_subject`
- `message_normalizations.full_message_text`
- `message_normalizations.source_provider`
- `message_normalizations.source_thread_id`
- `message_normalizations.source_message_id`
- `messages.body`
- `messages.subject`

Each fixture is stored as:

- `NNN_slug.source.json` — preserved inbound envelope plus deterministic mocked extraction fields
- `NNN_slug.expected.json` — locked-in expected parser output

## Redaction rules

These fixtures are committed to git, so the exporter applies deterministic redaction:

- Guest names become `Guest NNN`
- Guest email addresses become `guest_NNN@example.test`
- Phone numbers become `+1-555-0100`
- Property references become `Property_NNN`
- Platform listing ids become `listing_NNN`
- Platform unit ids become `unit_NNN`

Dates and the overall message structure stay intact because they matter to the parser.

## Adding a new fixture

1. Run `python3 scripts/build_inquiry_corpus.py`
2. Review the new or changed fixture pair
3. Run the replay test
4. If a real bug motivated the fixture, fix the parser or router in a separate commit
5. Commit the fixture and the fix together if the fixture is tied to a bug fix

## Naming

- Platform directories: `airbnb`, `vrbo`, `direct`
- Fixture files: `NNN_short_slug.source.json` and `NNN_short_slug.expected.json`
