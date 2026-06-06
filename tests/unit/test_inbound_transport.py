import asyncio
import base64
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from uuid import uuid4

from app.services.integrations.gmail_inbox_poller import GmailInboxPoller, GmailPollResult, ParsedGmailMessage
from app.services.integrations.email_inbound import EmailIntakeEnvelope
from app.services.integrations.llm_email_extractor import LLMEmailExtractorParseFailure
from app.services.messaging.inbound_normalizer import InboundMessageNormalizer
from app.services.messaging.inbound_transport import InboundTransportMode
from app.services.messaging.inbox_adapters import get_inbox_transport_capability


class _StubTokenManager:
    pass


def _gmail_message(*, msg_id: str, thread_id: str, headers: list[tuple[str, str]], plain_text: str) -> dict:
    return {
        "id": msg_id,
        "threadId": thread_id,
        "payload": {
            "headers": [{"name": name, "value": value} for name, value in headers],
            "body": {
                "data": base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("ascii")
            },
        },
    }


def test_transport_capability_registry_prefers_push_for_gmail_and_webhook_for_microsoft():
    gmail = get_inbox_transport_capability("gmail")
    microsoft = get_inbox_transport_capability("microsoft")

    assert gmail.preferred_mode == InboundTransportMode.PUSH_WATCH
    assert gmail.fallback_mode == InboundTransportMode.POLLING
    assert gmail.parser_required is True

    assert microsoft.preferred_mode == InboundTransportMode.WEBHOOK
    assert microsoft.fallback_mode == InboundTransportMode.POLLING
    assert microsoft.parser_required is True


def test_gmail_poller_exposes_transport_capability():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    capability = poller.transport_capability()

    assert capability.preferred_mode == InboundTransportMode.PUSH_WATCH
    assert capability.fallback_mode == InboundTransportMode.POLLING


def test_ota_inquiry_with_footer_boilerplate_is_not_misclassified_as_non_guest():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    plain_text = """
Property
External ID 2403-165151
#1673198

Unit
unit_2234599

Dates
Nov 18 - Dec 2, 2025, 14 nights

Guests
2 adults, 0 children

Traveler Name
Jan Hevey

Message from Jan Hevey

Many old reviews. Have you updated and when? Is parking still a problem?

Privacy Policy
Unsubscribe
"""
    gmail_message = {
        "id": "msg-123",
        "threadId": "thread-123",
        "payload": {
            "headers": [
                {"name": "From", "value": "Jan Hevey <sender@messages.homeaway.com>"},
                {"name": "Subject", "value": "Inquiry from Jan Hevey: Nov 18 - Dec 2, 2025 - Vrbo #1673198"},
                {"name": "Date", "value": "Tue, 30 Sep 2025 11:24:00 -0500"},
            ],
            "body": {
                "data": plain_text.encode("utf-8").hex()  # placeholder, replaced below
            },
        },
    }
    import base64
    gmail_message["payload"]["body"]["data"] = base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("ascii")

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is not None
    assert parsed.platform == "vrbo"
    assert parsed.guest_name == "Jan Hevey"
    assert "parking still a problem" in (((parsed.latest_guest_message or parsed.body) or "").lower())


def test_gmail_intake_stage_prepares_parsed_message_before_routing():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    parsed = ParsedGmailMessage(
        gmail_message_id="gmail-1",
        gmail_thread_id="thread-1",
        message_id_header="<message-1@example.com>",
        guest_name="Misty",
        guest_email="misty@example.com",
        subject="Question about the beach",
        body="Is the beach walkable?",
        latest_guest_message="Is the beach walkable?",
        platform="vrbo",
        is_inquiry=True,
        property_name="Sun Kissed on Hickory",
        property_code="",
    )

    async def _fake_get_full_message(msg_id, headers):
        return {"id": msg_id, "threadId": "thread-1", "payload": {}}

    async def _fake_parse(raw):
        return parsed

    async def _fake_prepare(parsed_message):
        parsed_message.property_code = "31Hickor"
        parsed_message.link_context_summary = "Nearby to the beach"
        return parsed_message

    poller._get_full_message = _fake_get_full_message
    poller._parse_with_ota_fallback = _fake_parse
    poller._prepare_parsed_message = _fake_prepare

    envelope = asyncio.run(
        poller._intake_message(
            "gmail-1",
            {"Authorization": "Bearer test"},
        )
    )

    assert envelope is not None
    assert envelope.source_message_id == "gmail-1"
    assert envelope.source_thread_id == "thread-1"
    assert envelope.parsed.property_code == "31Hickor"
    assert envelope.parsed.link_context_summary == "Nearby to the beach"


def test_gmail_parse_extracts_reply_headers():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    gmail_message = _gmail_message(
        msg_id="msg-reply-1",
        thread_id="thread-reply-1",
        headers=[
            ("From", "Monica Duvall <monica@example.com>"),
            ("Subject", "Re: 3 BY The Sea Question"),
            ("Message-ID", "<msg-reply-1@example.com>"),
            ("In-Reply-To", "<msg-root@example.com>"),
            ("References", "<msg-older@example.com> <msg-root@example.com>"),
            ("Date", "Thu, 07 May 2026 12:08:02 +0000"),
        ],
        plain_text="Can someone please let me know about parking before I sign the contract? Thanks",
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is not None
    assert parsed.in_reply_to == "<msg-root@example.com>"
    assert parsed.references == ["<msg-older@example.com>", "<msg-root@example.com>"]


def test_email_normalizer_uses_generic_email_channel_and_provider_specific_metadata():
    parsed = ParsedGmailMessage(
        source_provider="microsoft",
        source_message_id="graph-1",
        source_thread_id="conv-1",
        gmail_message_id="graph-1",
        gmail_thread_id="conv-1",
        message_id_header="<graph-1@example.com>",
        guest_name="Taylor",
        guest_email="taylor@example.com",
        subject="Question about parking",
        body="Is parking included?",
        latest_guest_message="Is parking included?",
        platform="vrbo",
        is_inquiry=True,
        property_name="Seabreeze",
        property_code="SB1",
    )

    normalized = InboundMessageNormalizer().normalize_email_message(parsed, watched_email="host@example.com")

    assert normalized.source_channel == "email"
    assert normalized.source_provider == "microsoft"
    assert normalized.source_message_id == "graph-1"
    assert normalized.source_thread_id == "conv-1"
    assert normalized.channel_constraints["source_message_id"] == "graph-1"
    assert normalized.channel_constraints["source_thread_id"] == "conv-1"


def test_gmail_push_history_poll_processes_only_changed_message_ids():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=SimpleNamespace(
            get_access_token=AsyncMock(return_value="token"),
            auth_header=lambda token: {"Authorization": f"Bearer {token}"},
        ),
        watched_email="info@example.com",
        db=None,
    )

    poller._list_history_message_ids = AsyncMock(return_value=["msg-new-1", "msg-new-2"])
    poller.poll_message_ids = AsyncMock(
        return_value=GmailPollResult(
            query_mode="gmail_history",
            messages_found=2,
            messages_processed=0,
            messages_skipped=0,
            pre_booking_routed=0,
            in_stay_routed=0,
            errors=[],
        )
    )

    result = asyncio.run(poller.poll_from_history("100", end_history_id="110"))

    assert result.query_mode == "gmail_history"
    poller._list_history_message_ids.assert_awaited_once()
    poller.poll_message_ids.assert_awaited_once_with(["msg-new-1", "msg-new-2"], query_mode="gmail_history")


def test_gmail_push_history_poll_falls_back_when_history_window_expired():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=SimpleNamespace(
            get_access_token=AsyncMock(return_value="token"),
            auth_header=lambda token: {"Authorization": f"Bearer {token}"},
        ),
        watched_email="info@example.com",
        db=None,
    )

    request = httpx.Request("GET", "https://gmail.test/users/me/history")
    response = httpx.Response(404, request=request)
    poller._list_history_message_ids = AsyncMock(side_effect=httpx.HTTPStatusError("gone", request=request, response=response))
    poller.poll_with_mode = AsyncMock(
        return_value=GmailPollResult(
            query_mode="recent_inbox",
            messages_found=0,
            messages_processed=0,
            messages_skipped=0,
            pre_booking_routed=0,
            in_stay_routed=0,
            errors=[],
        )
    )

    result = asyncio.run(poller.poll_from_history("100"))

    assert result.query_mode == "recent_inbox"
    poller.poll_with_mode.assert_awaited_once_with(query_mode="recent_inbox")


def test_prepare_parsed_message_inherits_property_when_resolution_empty(monkeypatch):
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id=uuid4(),
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=SimpleNamespace(),
    )
    parsed = ParsedGmailMessage(
        source_provider="gmail",
        source_message_id="msg-1",
        source_thread_id="thread-1",
        gmail_message_id="",
        gmail_thread_id="",
        message_id_header="<msg-1@example.com>",
        in_reply_to="<root@example.com>",
        references=["<older@example.com>", "<root@example.com>"],
        guest_name="Monica",
        guest_email="monica@example.com",
        subject="Re: 3 BY The Sea Question",
        body="Can someone please let me know about parking before I sign the contract? Thanks",
        latest_guest_message="Can someone please let me know about parking before I sign the contract? Thanks",
        platform="direct",
        is_inquiry=True,
        property_name="",
        property_code="",
    )

    monkeypatch.setattr(poller, "_resolve_property_code", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "app.services.concierge.thread_property_inheritance.inherit_property_from_thread_context",
        AsyncMock(
            return_value=SimpleNamespace(
                property_code="31GARD",
                inherited_from_message_id="prior-message",
                inherited_from_match_type="canonical_ref",
                inheritance_source="reply_headers",
            )
        ),
    )
    monkeypatch.setattr(poller, "_auto_store_property_identity", AsyncMock())
    monkeypatch.setattr(poller, "_maybe_record_unmatched_platform_identifier", AsyncMock())
    monkeypatch.setattr(poller, "_enrich_with_link_context", AsyncMock())
    monkeypatch.setattr(poller, "_shadow_persist_canonical_message", AsyncMock())

    result = asyncio.run(poller._prepare_parsed_message(parsed))

    assert result.property_code == "31GARD"
    assert result.property_match_type == "thread_inheritance"


def test_prepare_parsed_message_keeps_explicit_property_over_inheritance(monkeypatch):
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id=uuid4(),
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=SimpleNamespace(),
    )
    parsed = ParsedGmailMessage(
        source_provider="gmail",
        source_message_id="msg-1",
        source_thread_id="thread-1",
        gmail_message_id="",
        gmail_thread_id="",
        message_id_header="<msg-1@example.com>",
        in_reply_to="<root@example.com>",
        references=["<older@example.com>", "<root@example.com>"],
        guest_name="Monica",
        guest_email="monica@example.com",
        subject="Re: 3 BY The Sea Question",
        body="Can someone please let me know about parking before I sign the contract? Thanks",
        latest_guest_message="Can someone please let me know about parking before I sign the contract? Thanks",
        platform="direct",
        is_inquiry=True,
        property_name="3 By The Sea",
        property_code="",
    )

    inherited = AsyncMock()
    monkeypatch.setattr(poller, "_resolve_property_code", AsyncMock(return_value="31GARD"))
    monkeypatch.setattr(
        "app.services.concierge.thread_property_inheritance.inherit_property_from_thread_context",
        inherited,
    )
    monkeypatch.setattr(poller, "_auto_store_property_identity", AsyncMock())
    monkeypatch.setattr(poller, "_maybe_record_unmatched_platform_identifier", AsyncMock())
    monkeypatch.setattr(poller, "_enrich_with_link_context", AsyncMock())
    monkeypatch.setattr(poller, "_shadow_persist_canonical_message", AsyncMock())

    result = asyncio.run(poller._prepare_parsed_message(parsed))

    assert result.property_code == "31GARD"
    assert result.property_match_type == ""
    inherited.assert_not_awaited()


def test_process_one_message_records_rfc_message_id(monkeypatch):
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )
    parsed = ParsedGmailMessage(
        source_provider="gmail",
        source_message_id="msg-1",
        source_thread_id="thread-1",
        gmail_message_id="msg-1",
        gmail_thread_id="thread-1",
        message_id_header="<message-rfc@example.com>",
        guest_name="Guest",
        guest_email="guest@example.com",
        subject="Question",
        body="Can we check in early?",
        latest_guest_message="Can we check in early?",
        platform="vrbo",
        is_inquiry=True,
        property_name="Seabreeze",
        property_code="SB1",
    )

    async def _fake_is_already_processed(_msg_id):
        return False

    async def _fake_get_full_message(_msg_id, _headers):
        return {"id": _msg_id, "threadId": "thread-1", "payload": {}}

    async def _fake_intake_raw_message(_raw, *, msg_id, headers):
        return EmailIntakeEnvelope(
            parsed=parsed,
            source_message_id=parsed.message_id,
            source_thread_id=parsed.thread_id,
        )

    async def _fake_route_message(_parsed):
        return "pre_booking_new"

    poller._is_already_processed = _fake_is_already_processed
    poller._get_full_message = _fake_get_full_message
    poller._intake_raw_message = _fake_intake_raw_message
    poller._route_message = _fake_route_message
    poller._mark_processed = AsyncMock()
    poller._ensure_processed_label = AsyncMock()
    poller._apply_label = AsyncMock()

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-1", {}, result))

    poller._mark_processed.assert_awaited_once_with("msg-1", "<message-rfc@example.com>", {})
    poller._ensure_processed_label.assert_awaited_once_with({})
    poller._apply_label.assert_awaited_once_with("msg-1", {})


def test_process_one_message_skips_pre_live_mailbox_backlog():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    raw_message = _gmail_message(
        msg_id="msg-old-1",
        thread_id="thread-old-1",
        headers=[
            ("From", "Guest <guest@example.com>"),
            ("Subject", "Older unread message"),
            ("Date", "Tue, 27 May 2026 12:00:00 +0000"),
        ],
        plain_text="This was in the inbox before go-live.",
    )

    async def _fake_is_already_processed(_msg_id):
        return False

    async def _fake_get_full_message(_msg_id, _headers):
        return raw_message

    async def _fake_load_go_live():
        return datetime(2026, 5, 28, 0, 0, 0)

    poller._is_already_processed = _fake_is_already_processed
    poller._get_full_message = _fake_get_full_message
    poller._load_inbox_go_live_at = _fake_load_go_live
    poller._record_processing_state = AsyncMock()
    poller._intake_raw_message = AsyncMock()
    poller._mark_processed = AsyncMock()
    poller._ensure_processed_label = AsyncMock()
    poller._apply_label = AsyncMock()

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-old-1", {"Authorization": "Bearer test"}, result))

    assert result.messages_processed == 0
    assert result.messages_skipped == 1
    assert result.pre_live_skips == 1
    poller._intake_raw_message.assert_not_awaited()
    poller._mark_processed.assert_not_awaited()
    poller._record_processing_state.assert_awaited_once()
    assert poller._record_processing_state.await_args.kwargs["failure_reason"] == "pre_live_cutoff"


def test_parse_failure_blocks_routing_and_counts_skip():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    async def _fake_is_already_processed(msg_id):
        return False

    async def _fake_get_full_message(_msg_id, _headers):
        return {"id": _msg_id, "threadId": "thread-parse-fail", "payload": {}}

    async def _fake_intake_raw_message(_raw, *, msg_id, headers):
        raise LLMEmailExtractorParseFailure("empty_latest_guest_message")

    poller._is_already_processed = _fake_is_already_processed
    poller._get_full_message = _fake_get_full_message
    poller._intake_raw_message = _fake_intake_raw_message
    poller._mark_processed = AsyncMock()
    poller._ensure_processed_label = AsyncMock()
    poller._apply_label = AsyncMock()

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-parse-fail", {}, result))

    assert result.messages_processed == 0
    assert result.messages_skipped == 1
    assert result.parse_failure_skips == 1
    poller._mark_processed.assert_not_awaited()
    poller._ensure_processed_label.assert_not_awaited()
    poller._apply_label.assert_not_awaited()


def test_parse_failure_quarantines_after_threshold():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    async def _fake_is_already_processed(msg_id):
        return False

    async def _fake_get_full_message(_msg_id, _headers):
        return {"id": _msg_id, "threadId": "thread-quarantine", "payload": {}}

    async def _fake_intake_raw_message(_raw, *, msg_id, headers):
        raise LLMEmailExtractorParseFailure("empty_latest_guest_message")

    poller._is_already_processed = _fake_is_already_processed
    poller._get_full_message = _fake_get_full_message
    poller._intake_raw_message = _fake_intake_raw_message
    poller._record_retryable_failure = AsyncMock(return_value=("quarantined", 3))

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-quarantine", {}, result))

    assert result.messages_processed == 0
    assert result.messages_skipped == 1
    assert result.parse_failure_skips == 1
    assert result.quarantined_skips == 1
    poller._record_retryable_failure.assert_awaited_once()


def test_generic_gmail_parser_upgrades_booked_contract_email_to_pre_arrival():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    gmail_message = _gmail_message(
        msg_id="msg-booked-1",
        thread_id="thread-booked-1",
        headers=[
            ("From", "Amber Barry <ajallen26@mac.com>"),
            ("Subject", "Need to sign contract"),
            ("Message-ID", "<amber@example.com>"),
            ("Date", "Mon, 25 May 2026 13:00:00 +0000"),
        ],
        plain_text=(
            "This is Amber Barry. I’m booked for close enough on June 27th. "
            "You all sent me a email to sign a contract and I cannot find that email now. "
            "Just wanted to make sure that all is well with our reservation. Thank you"
        ),
    )

    parsed = poller._parser.parse(gmail_message)

    assert parsed is not None
    assert parsed.lifecycle_stage == "pre_arrival"


def test_generic_gmail_parser_upgrades_operational_stay_email_to_in_stay():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    gmail_message = _gmail_message(
        msg_id="msg-stay-1",
        thread_id="thread-stay-1",
        headers=[
            ("From", "Natalie Horton <nataliedhorton@icloud.com>"),
            ("Subject", "Where to charge golf cart"),
            ("Message-ID", "<natalie@example.com>"),
            ("Date", "Tue, 26 May 2026 12:50:00 +0000"),
        ],
        plain_text=(
            "Good morning,\n"
            "We can’t find any outside wall outlets to charge the golf cart that we rented "
            "from the approved golf cart rental place.\n\n"
            "Where do people who stay at this house, charge?"
        ),
    )

    parsed = poller._parser.parse(gmail_message)

    assert parsed is not None
    assert parsed.lifecycle_stage == "in_stay"


def test_non_guest_message_is_recorded_as_terminal_seen_state():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    async def _fake_is_already_processed(msg_id):
        return False

    async def _fake_get_full_message(_msg_id, _headers):
        return {"id": _msg_id, "threadId": "thread-non-guest", "payload": {}}

    async def _fake_intake_raw_message(_raw, *, msg_id, headers):
        poller._last_non_guest_reason = "pattern:airbnb_review_notification"
        return None

    poller._is_already_processed = _fake_is_already_processed
    poller._get_full_message = _fake_get_full_message
    poller._intake_raw_message = _fake_intake_raw_message
    poller._record_processing_state = AsyncMock()

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-non-guest", {"Authorization": "Bearer test"}, result))

    assert result.messages_processed == 0
    assert result.messages_skipped == 1
    assert result.non_guest_skips == 1
    poller._record_processing_state.assert_awaited_once()
    assert poller._record_processing_state.await_args.kwargs["failure_reason"] == "pattern:airbnb_review_notification"


def test_quarantined_message_counts_as_quarantine_skip():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    async def _fake_is_already_processed(msg_id):
        return True

    async def _fake_get_processing_record(msg_id):
        return {"processing_status": "quarantined", "failure_count": 3}

    poller._is_already_processed = _fake_is_already_processed
    poller._get_processing_record = _fake_get_processing_record

    result = GmailPollResult(
        messages_found=1,
        messages_processed=0,
        messages_skipped=0,
        pre_booking_routed=0,
        in_stay_routed=0,
        errors=[],
    )

    asyncio.run(poller._process_one_message("msg-seen", {}, result))

    assert result.messages_processed == 0
    assert result.messages_skipped == 1
    assert result.quarantined_skips == 1


def test_vrbo_replied_message_hands_off_to_parser_layer():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    plain_text = """
Vrbo: Rebecca and Mason Reeves has replied to your message

Great! I just filled it out. It would also be great to get an earlier check in than 4 pm if possible.
"""
    gmail_message = _gmail_message(
        msg_id="msg-vrbo-replied",
        thread_id="thread-vrbo-replied",
        headers=[
            ("From", "Rebecca and Mason Reeves <sender@messages.homeaway.com>"),
            ("Reply-To", "Rebecca and Mason Reeves <abc123@messages.homeaway.com>"),
            ("Subject", "Reservation from Rebecca and Mason Reeves: Aug 1 - Aug 8, 2026 - Vrbo #1416282"),
            ("X-Mediated-Site", "vrbo"),
            ("X-Mediated-Message-Type", "REPLIED"),
            ("X-Mediated-Conversation-ID", "/conversations/0030/example"),
            ("X-Mediated-Reservation-ID", "/reservations/0030/example"),
            ("Date", "Thu, 07 May 2026 12:08:02 +0000"),
        ],
        plain_text=plain_text,
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is not None
    assert parsed.intake_layer1_decision == "unclear"
    assert parsed.message_type == "REPLIED"
    assert parsed.ota_site == "vrbo"


def test_vrbo_new_inquiry_admits_and_preserves_ota_metadata():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    plain_text = """
Property
External ID 2403-250642
#3350889

Unit
unit_3924014
Guests
2 adults, 0 children
Traveler Name
Misty Kettinger
Inquiry from:
Vrbo

Further info

Hi, we are checking in on May 16. I was wondering if early check in is a possibility.
"""
    gmail_message = _gmail_message(
        msg_id="msg-vrbo-inquiry",
        thread_id="thread-vrbo-inquiry",
        headers=[
            ("From", "Misty Kettinger <sender@messages.homeaway.com>"),
            ("Reply-To", "Misty Kettinger <ae0c9666-0b0b-4dcc-b602-0ab410680720@messages.homeaway.com>"),
            ("Subject", "Inquiry from Misty Kettinger: Vrbo #3350889"),
            ("X-Mediated-Site", "vrbo"),
            ("X-Mediated-Message-Type", "NEW_INQUIRY"),
            ("X-Mediated-Conversation-ID", "/conversations/0030/example"),
            ("X-Mediated-Reservation-ID", "/reservations/0030/example"),
            ("X-Mediated-Recipient-Type", "OWNER"),
            ("Date", "Tue, 30 Sep 2025 11:24:00 -0500"),
        ],
        plain_text=plain_text,
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is not None
    assert parsed.intake_layer1_decision == "admit"
    assert parsed.intake_layer1_reason == "ota_message_type:NEW_INQUIRY"
    assert parsed.ota_site == "vrbo"
    assert parsed.message_type == "NEW_INQUIRY"
    assert parsed.conversation_id == "/conversations/0030/example"
    assert parsed.reservation_id == "/reservations/0030/example"
    assert parsed.recipient_type == "OWNER"


def test_internal_operator_sender_is_dropped_by_layer1():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    gmail_message = _gmail_message(
        msg_id="msg-internal",
        thread_id="thread-internal",
        headers=[
            ("From", "Tiffany Werner <twerner@cmacommunities.com>"),
            ("Subject", "Preserve at Grayton Beach"),
            ("Date", "Thu, 07 May 2026 12:08:02 +0000"),
        ],
        plain_text="We will be changing the Tennis Courts, Pools, Bathrooms, and Beach codes this Friday.",
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is None


def test_vrbo_reservation_confirmed_hands_off_to_parser_layer():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    gmail_message = _gmail_message(
        msg_id="msg-vrbo-res-confirmed",
        thread_id="thread-vrbo-res-confirmed",
        headers=[
            ("From", "Vrbo <sender@messages.homeaway.com>"),
            ("Reply-To", "guest-thread@messages.homeaway.com"),
            ("Subject", "Reservation confirmed - Steven Sikora arrives Aug 19"),
            ("X-Mediated-Site", "vrbo"),
            ("X-Mediated-Message-Type", "RESERVATION_CONFIRMED"),
            ("Date", "Thu, 07 May 2026 12:08:02 +0000"),
        ],
        plain_text="Reservation confirmed event",
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is not None
    assert parsed.intake_layer1_decision == "unclear"
    assert parsed.system_generated is True
    assert parsed.message_type == "RESERVATION_CONFIRMED"


def test_markup_noise_is_dropped_by_layer1():
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id="00000000-0000-0000-0000-000000000001",
        token_manager=_StubTokenManager(),
        watched_email="info@example.com",
        db=None,
    )

    plain_text = """
/* making this same as default so no hover effects are visible for now */
a:hover {
  color: #2a6ebb !important;
}
a:active {
  color: #2a6ebb !important;
}
a:visited {
  color: #2a6ebb !important;
}
h1 a:active {
  color: #0C6DAC !important;
}
"""
    gmail_message = _gmail_message(
        msg_id="msg-css",
        thread_id="thread-css",
        headers=[
            ("From", "Guest <sender@homeaway.com>"),
            ("Subject", ""),
            ("Date", "Thu, 07 May 2026 12:08:02 +0000"),
        ],
        plain_text=plain_text,
    )

    parsed = asyncio.run(poller._parse_with_ota_fallback(gmail_message))

    assert parsed is None
