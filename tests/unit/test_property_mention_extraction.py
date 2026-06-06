from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.integrations.gmail_inbox_poller import (
    GmailEmailParser,
    GmailInboxPoller,
    ParsedGmailMessage,
)
from app.services.integrations.property_mention_surfaces import (
    SURFACE_QUOTED_CONTEXT,
    SURFACE_SUBJECT,
    extract_property_mention_candidates,
    select_best_candidate,
)
from app.services.property_canonical_service import CanonicalPropertyService


class _FakeFetchOneResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeMappingsResult:
    def first(self):
        return None


class _SuggestionOnlySession:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "FROM canonical_property_refs" in sql:
            return _FakeFetchOneResult(None)
        if "FROM properties" in sql and "LIMIT 1" in sql:
            return _FakeFetchOneResult(None)
        if "FROM pms_listings" in sql and "LIMIT 1" in sql:
            return _FakeFetchOneResult(None)
        if "FROM information_schema.columns" in sql:
            return _FakeFetchOneResult(None)
        return _FakeMappingsResult()


class _ExternalIdFallbackSession:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        copied = dict(params) if isinstance(params, dict) else params
        self.calls.append((sql, copied))
        if "FROM canonical_property_refs" in sql:
            return _FakeFetchOneResult(None)
        if "FROM properties" in sql and "LIMIT 1" in sql:
            if params and params.get("external_id") == "280970":
                return _FakeFetchOneResult(("BH5089865",))
            return _FakeFetchOneResult(None)
        if "FROM pms_listings" in sql and "LIMIT 1" in sql:
            return _FakeFetchOneResult(None)
        if "FROM information_schema.columns" in sql:
            return _FakeFetchOneResult(None)
        return _FakeMappingsResult()


class _StubTokenManager:
    pass


def _sample_parsed_gmail(**overrides) -> ParsedGmailMessage:
    payload = {
        "source_provider": "gmail",
        "source_message_id": "gmail-msg-123",
        "source_thread_id": "gmail-thread-123",
        "gmail_message_id": "gmail-msg-123",
        "gmail_thread_id": "gmail-thread-123",
        "message_id_header": "<gmail-msg-123@example.com>",
        "guest_name": "Guest",
        "guest_email": "guest@example.com",
        "sender_role": "guest",
        "reply_channel_address": "guest@example.com",
        "subject": "Question",
        "body": "Body",
        "latest_guest_message": "Body",
        "conversation_context": "",
        "full_body": "Body",
        "asks": [],
        "platform": "direct",
        "is_inquiry": True,
        "parser_source": "generic_gmail_parser",
        "property_name": "",
        "raw_property_mention": "",
        "property_code": "",
        "platform_listing_id": "",
        "platform_unit_id": "",
    }
    payload.update(overrides)
    return ParsedGmailMessage(**payload)


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_binds_294_spartina_circle(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "294 spartina circle"
        return [
            {"property_code": "294SC", "score": 0.88, "matched_on": "address_street"},
            {"property_code": "359SC", "score": 0.6667, "matched_on": "address_street"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="294 spartina circle",
        platform="direct",
    )

    assert resolved == "294SC"


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_binds_132_east_kingston_road(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "132 East Kingston Road"
        return [
            {"property_code": "132EKR", "score": 0.50, "matched_on": "address_street"},
            {"property_code": "42WK", "score": 0.275, "matched_on": "address_street"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="132 East Kingston Road",
        platform="direct",
    )

    assert resolved == "132EKR"


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_binds_17_lyonia(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "17 Lyonia"
        return [
            {"property_code": "17LL", "score": 0.92, "matched_on": "address_street"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="17 Lyonia",
        platform="direct",
    )

    assert resolved == "17LL"


@pytest.mark.asyncio
async def test_resolve_property_code_external_id_hint_falls_back_to_suffix_match():
    session = _ExternalIdFallbackSession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="ExternalID:2403-280970",
        platform="vrbo",
    )

    assert resolved == "BH5089865"
    property_external_id_attempts = [
        params.get("external_id")
        for sql, params in session.calls
        if "FROM properties" in sql and params and "external_id" in params
    ]
    assert property_external_id_attempts == ["2403-280970", "280970"]


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_binds_359_spartina_circle(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "359 Spartina Circle"
        return [
            {"property_code": "359SC", "score": 1.0, "matched_on": "address_street"},
            {"property_code": "294SC", "score": 0.6667, "matched_on": "address_street"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="359 Spartina Circle",
        platform="direct",
    )

    assert resolved == "359SC"


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_declines_vague_input(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "the beach house"
        return [
            {"property_code": "31GARD", "score": 0.2833, "matched_on": "property_name"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="the beach house",
        platform="direct",
    )

    assert resolved == ""


@pytest.mark.asyncio
async def test_resolve_property_code_token_fallback_declines_close_runner_up(monkeypatch):
    session = _SuggestionOnlySession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    async def _fake_suggestions(self, tenant_id, raw_value, *, limit=5):
        assert raw_value == "Spartina house"
        return [
            {"property_code": "294SC", "score": 0.55, "matched_on": "address_street"},
            {"property_code": "359SC", "score": 0.48, "matched_on": "address_street"},
        ]

    monkeypatch.setattr(CanonicalPropertyService, "suggest_property_matches", _fake_suggestions)

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="Spartina house",
        platform="direct",
    )

    assert resolved == ""


def test_extract_body_property_mention_finds_294_spartina_circle():
    parser = GmailEmailParser()
    body = (
        "Good afternoon, We have rented a home starting tomorrow and asked for 4 wrist bands; "
        "however, we have two additional adults coming for 24 hours and will need two additional "
        "wrist bands. Is there a place I can request two more? We are staying at 294 spartina "
        "circle. Thank you, Catherine Lowe"
    )

    extracted = parser._extract_body_property_mention(body)

    assert extracted == "294 spartina circle"


def test_extract_body_property_mention_finds_132_east_kingston_road():
    parser = GmailEmailParser()
    body = (
        "Hi! We're arriving at 132 East Kingston Road on Sunday May 17.\n\n"
        "I'd like to request an early check-in of around 1pm that day."
    )

    extracted = parser._extract_body_property_mention(body)

    assert extracted == "132 East Kingston Road"


def test_extract_body_property_mention_finds_17_lyonia():
    parser = GmailEmailParser()
    body = "Hey guys! Can we book 17 Lyonia May 13-18 at the best available rate for us?"

    extracted = parser._extract_body_property_mention(body)

    # Outage-mode best-effort; the LLM extractor owns this case on the normal path.
    assert extracted == "17 Lyonia"


def test_extract_body_property_mention_returns_empty_for_follow_up():
    parser = GmailEmailParser()

    assert parser._extract_body_property_mention("OK - thank you!") == ""


def test_surface_candidates_pick_subject_when_body_omits_property():
    candidates = extract_property_mention_candidates(
        subject="Re: Payment due notice for 100 S Spooky Lane Unit 2D",
        latest_body="Hello, can you confirm if the unit has a high chair and pack and play?",
        quoted_context="",
    )

    best = select_best_candidate(candidates)

    assert best is not None
    assert best.surface == SURFACE_SUBJECT
    assert best.mention == "100 S Spooky Lane Unit 2D"


def test_surface_candidates_pick_quoted_context_when_latest_body_omits_property():
    candidates = extract_property_mention_candidates(
        subject="Re: Quick question",
        latest_body="Can you confirm if there is a baby gate?",
        quoted_context="Original message\nWe are staying at 100 S Spooky Lane Unit 2D next week.",
    )

    best = select_best_candidate(candidates)

    assert best is not None
    assert best.surface == SURFACE_QUOTED_CONTEXT
    assert best.mention == "100 S Spooky Lane Unit 2D"


def test_gmail_parser_records_subject_surface_audit_for_christina_shape():
    parser = GmailEmailParser()
    gmail_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: Payment due notice for 100 S Spooky Lane Unit 2D"},
                {"name": "From", "value": "Christina <guest@example.com>"},
                {"name": "Date", "value": "Mon, 18 May 2026 12:00:00 +0000"},
                {"name": "Message-ID", "value": "<msg-1@example.com>"},
            ],
            "body": {
                "data": "SGVsbG8tIGNhbiB5b3UgY29uZmlybSBpZiB0aGUgdW5pdCBoYXMgdGhlIGZvbGxvd2luZz8gSGlnaCBjaGFpciBQYWNrIGFuZCBwbGF5IEJhYnkgZ2F0ZSBCZWFjaCB0b3lzIEJlYWNoIGNoYWlycw=="
            },
        },
    }

    parsed = parser.parse(gmail_message)

    assert parsed is not None
    assert parsed.property_name == "100 S Spooky Lane Unit 2D"
    assert parsed.property_mention_surface_audit["selected_surface"] == SURFACE_SUBJECT


def test_gmail_parser_surface_selector_uses_quoted_context_when_available():
    parser = GmailEmailParser()
    property_name, audit = parser._select_property_mention_across_surfaces(
        subject="Re: Quick question",
        body="Can you confirm if there is a baby gate?",
        latest_body="Can you confirm if there is a baby gate?",
        quoted_context="We are staying at 100 S Spooky Lane Unit 2D next week.",
    )

    assert property_name == "100 S Spooky Lane Unit 2D"
    assert audit["selected_surface"] == SURFACE_QUOTED_CONTEXT


def test_token_scored_resolve_still_queues_operator_review(monkeypatch):
    observed_calls = []
    review_calls = []

    class _FakeWriter:
        async def observe_resolved_identity(self, *args, **kwargs):
            observed_calls.append((args, kwargs))

        async def queue_property_link_review(self, *args, **kwargs):
            review_calls.append((args, kwargs))

    async def _fake_load_property_context(self, property_code):
        assert property_code == "294SC"
        return (
            {
                "property_name": "294 Spartina Cir",
                "display_name": "294 Spartina Cir",
                "preferred_address": "294 Spartina Cir",
                "address_street": "294 Spartina Cir",
            },
            {},
        )

    async def _fake_assessment(self, parsed):
        assert parsed.property_code == "294SC"
        return {
            "auto_store": False,
            "confidence": 0.88,
            "reason": "needs_operator_review",
            "candidates": [
                {"property_code": "294SC", "score": 0.88},
                {"property_code": "359SC", "score": 0.6667},
            ],
        }

    monkeypatch.setattr(
        "app.services.integrations.gmail_inbox_poller.get_canonical_property_write_service",
        lambda db: _FakeWriter(),
    )
    monkeypatch.setattr(GmailInboxPoller, "_load_property_context", _fake_load_property_context)
    monkeypatch.setattr(GmailInboxPoller, "_assess_property_identity_confidence", _fake_assessment)

    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id=UUID("00000000-0000-0000-0000-000000000001"),
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=SimpleNamespace(),
    )
    parsed = _sample_parsed_gmail(
        property_code="294SC",
        property_name="294 spartina circle",
        raw_property_mention="294 spartina circle",
    )

    asyncio.run(poller._auto_store_property_identity(parsed))

    assert not observed_calls
    assert review_calls
    args, kwargs = review_calls[0]
    assert kwargs["canonical_property_code"] == "294SC"
    assert kwargs["confidence"] == 0.88
    assert kwargs["ref_value"] == "294 spartina circle"
    assert kwargs["source"] == "gmail_identity_review"
