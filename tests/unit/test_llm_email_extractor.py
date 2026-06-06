import pytest

from app.services.integrations.llm_email_extractor import (
    LLMEmailExtractor,
    LLMEmailExtractorFallback,
    LLMEmailExtractorParseFailure,
    _ProviderResponse,
)


def _ok_payload(message: str = "Hi, is the pool heated in October?") -> str:
    return f"""
    {{
      "latest_guest_message": "{message}",
      "property_code_or_name": "Sea La Vie",
      "requested_check_in": "2026-10-10",
      "requested_check_out": "2026-10-14",
      "requested_guests": 4,
      "sender_email": "guest@example.com",
      "sender_name": "Misty"
    }}
    """


@pytest.mark.asyncio
async def test_extractor_prefers_groq_when_available_and_successful():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="groq-key")
    groq_calls: list[str] = []
    anthropic_calls: list[str] = []
    records: list[dict] = []

    async def _fake_groq(prompt: str) -> str:
        groq_calls.append(prompt)
        return _ProviderResponse(text=_ok_payload("Hi, is parking included?"), input_tokens=10, output_tokens=5)

    async def _fake_anthropic(prompt: str) -> str:
        anthropic_calls.append(prompt)
        return _ProviderResponse(text=_ok_payload("Anthropic should not run"), input_tokens=1, output_tokens=1)

    extractor._call_groq = _fake_groq
    extractor._call_anthropic = _fake_anthropic
    from app.services.observability.llm_usage_tracker import LLMUsageTracker
    original = LLMUsageTracker.record
    async def _fake_record(**kwargs):
        records.append(kwargs)
    LLMUsageTracker.record = _fake_record

    try:
        result = await extractor.extract(
            source_message_id="msg-1",
            detected_shape="vrbo",
            subject="Question",
            plain_text="Hi, is parking included?",
            raw_html="",
            headers={},
        )
    finally:
        LLMUsageTracker.record = original

    assert result.latest_guest_message == "Hi, is parking included?"
    assert result.raw_property_mention == "Sea La Vie"
    assert result.requested_guests == 4
    assert result.sender_email == "guest@example.com"
    assert result.parser_source == "llm_email_extractor_groq"
    assert result.property_mention_surface_audit is not None
    assert result.property_mention_surface_audit["type"] == "property_mention_surface_audit"
    assert len(groq_calls) == 1
    assert anthropic_calls == []
    assert records[0]["provider"] == "groq"
    assert records[0]["success"] is True


@pytest.mark.asyncio
async def test_extractor_falls_back_to_anthropic_on_groq_http_error():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="groq-key")
    groq_calls: list[str] = []
    anthropic_calls: list[str] = []
    records: list[dict] = []

    async def _fake_groq(prompt: str) -> str:
        groq_calls.append(prompt)
        raise LLMEmailExtractorFallback("api_error:HTTPStatusError")

    async def _fake_anthropic(prompt: str) -> str:
        anthropic_calls.append(prompt)
        return _ProviderResponse(text=_ok_payload("Anthropic fallback result"), input_tokens=20, output_tokens=7)

    extractor._call_groq = _fake_groq
    extractor._call_anthropic = _fake_anthropic
    from app.services.observability.llm_usage_tracker import LLMUsageTracker
    original = LLMUsageTracker.record
    async def _fake_record(**kwargs):
        records.append(kwargs)
    LLMUsageTracker.record = _fake_record

    try:
        result = await extractor.extract(
            source_message_id="msg-2",
            detected_shape="generic",
            subject="Question",
            plain_text="Can we bring a dog?",
            raw_html="",
            headers={},
        )
    finally:
        LLMUsageTracker.record = original

    assert result.latest_guest_message == "Anthropic fallback result"
    assert result.parser_source == "llm_email_extractor_anthropic"
    assert len(groq_calls) == 1
    assert len(anthropic_calls) == 1
    assert [r["provider"] for r in records] == ["groq", "anthropic"]
    assert records[0]["success"] is False
    assert records[1]["success"] is True


@pytest.mark.asyncio
async def test_extractor_falls_back_to_anthropic_on_groq_timeout():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="groq-key")
    groq_calls: list[str] = []
    anthropic_calls: list[str] = []

    async def _fake_groq(prompt: str) -> str:
        groq_calls.append(prompt)
        raise LLMEmailExtractorFallback("timeout")

    async def _fake_anthropic(prompt: str) -> str:
        anthropic_calls.append(prompt)
        return _ProviderResponse(text=_ok_payload("Anthropic after timeout"), input_tokens=20, output_tokens=7)

    extractor._call_groq = _fake_groq
    extractor._call_anthropic = _fake_anthropic

    result = await extractor.extract(
        source_message_id="msg-3",
        detected_shape="generic",
        subject="Question",
        plain_text="Is the beach private?",
        raw_html="",
        headers={},
    )

    assert result.latest_guest_message == "Anthropic after timeout"
    assert result.parser_source == "llm_email_extractor_anthropic"
    assert len(groq_calls) == 1
    assert len(anthropic_calls) == 1


@pytest.mark.asyncio
async def test_extractor_raises_last_fallback_when_both_providers_fail():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="groq-key")

    async def _fake_groq(prompt: str) -> str:
        raise LLMEmailExtractorFallback("timeout")

    async def _fake_anthropic(prompt: str) -> str:
        raise LLMEmailExtractorFallback("api_error:HTTPStatusError")

    extractor._call_groq = _fake_groq
    extractor._call_anthropic = _fake_anthropic

    with pytest.raises(LLMEmailExtractorFallback) as exc:
        await extractor.extract(
            source_message_id="msg-4",
            detected_shape="generic",
            subject="Question",
            plain_text="hello",
            raw_html="",
            headers={},
        )

    assert exc.value.reason == "anthropic:api_error:HTTPStatusError"


@pytest.mark.asyncio
async def test_extractor_raises_fallback_on_invalid_json():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="")

    async def _fake_call(prompt: str) -> str:
        return _ProviderResponse(text="not-json")

    extractor._call_anthropic = _fake_call

    with pytest.raises(LLMEmailExtractorFallback):
        await extractor.extract(
            source_message_id="msg-5",
            detected_shape="generic",
            subject="Question",
            plain_text="hello",
            raw_html="",
            headers={},
        )


@pytest.mark.asyncio
async def test_extractor_raises_parse_failure_on_empty_latest_guest_message():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="")

    async def _fake_call(prompt: str) -> str:
        return _ProviderResponse(text="""
        {
          "latest_guest_message": null,
          "property_code_or_name": null,
          "requested_check_in": null,
          "requested_check_out": null,
          "requested_guests": null,
          "sender_email": null,
          "sender_name": null
        }
        """)

    extractor._call_anthropic = _fake_call

    with pytest.raises(LLMEmailExtractorParseFailure):
        await extractor.extract(
            source_message_id="msg-6",
            detected_shape="generic",
            subject="Automatic reply",
            plain_text="Out of office",
            raw_html="",
            headers={},
        )


@pytest.mark.asyncio
async def test_extractor_supplements_structured_identity_hints_from_email_text():
    extractor = LLMEmailExtractor(anthropic_key="anth-key", groq_key="")

    async def _fake_call(prompt: str) -> str:
        return _ProviderResponse(text="""
        {
          "latest_guest_message": "Hello! Can you please explain the layout of the condo?",
          "property_code_or_name": "#4300735",
          "requested_check_in": "2026-06-09",
          "requested_check_out": "2026-06-14",
          "requested_guests": 2,
          "sender_email": "guest@example.com",
          "sender_name": "Melanie Tarbush"
        }
        """)

    extractor._call_anthropic = _fake_call

    result = await extractor.extract(
        source_message_id="msg-7",
        detected_shape="ota:vrbo",
        subject="Inquiry from Melanie Tarbush: Jun 9 - Jun 14, 2026 - Vrbo #4300735",
        plain_text="""
Property
External ID 2403-268707 #4300735
Unit
unit_4874905
Dates
Jun 9 - Jun 14, 2026, 5 nights
Guests
2 adults

Further info
Hello! Can you please explain the layout of the condo?
Respond to this Inquiry
""",
        raw_html="",
        headers={},
    )

    assert result.raw_property_mention == "#4300735"
    assert result.platform_listing_id == "4300735"
    assert result.platform_unit_id == "unit_4874905"
    assert result.external_id_hint == "ExternalID:2403-268707"
    assert result.provider_account_id == "2403"
    assert result.provider_property_id == "268707"
    assert result.source_property_id == "268707"
