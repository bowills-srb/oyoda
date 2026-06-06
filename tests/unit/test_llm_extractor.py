from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from app.services.extraction.canonical_block_service import CanonicalBlock
from app.services.extraction.chunkers import ChunkedContent
from app.services.extraction.llm_extractor import LLMExtractor


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")


class StubLLMExtractor(LLMExtractor):
    def __init__(self, responses):
        super().__init__(anthropic_api_key="test-key")
        self._responses = list(responses)
        self.sleep_calls: list[float] = []
        self.jitter_value = 0.0

    async def _call_anthropic(self, *, system_prompt: str, user_prompt: str):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def _sleep(self, delay: float) -> None:
        self.sleep_calls.append(delay)

    def _jitter_seconds(self) -> float:
        return self.jitter_value


def _canonical_block(render_type: str = "guide_content.faqs", scope_type: str = "tenant") -> CanonicalBlock:
    return CanonicalBlock(
        block_hash="abc123def456",
        render_type=render_type,
        tenant_id=TENANT_ID,
        canonical_source_property_id=PROPERTY_ID,
        canonical_page_id=24793,
        applicable_property_ids=[PROPERTY_ID],
        scope_type=scope_type,
        duplicate_group_metadata=None,
        duplicate_count=1,
        block_content={
            "id": 99,
            "render_type": render_type,
            "title": "FAQs",
            "page_title": "FAQs",
            "data": {"content": "<p>Example</p>"},
        },
    )


def _chunk(
    *,
    section_title: str = "What is your cancellation policy?",
    content_html: str = "<p>Cancel 60+ days before arrival for a full refund.</p>",
    content_text: str = "Cancel 60+ days before arrival for a full refund.",
) -> ChunkedContent:
    return ChunkedContent(
        chunk_id="chunk-1",
        source_block_hash="abc123def456",
        section_title=section_title,
        order_within_block=0,
        content_html=content_html,
        content_text=content_text,
        metadata={"question_tag": "p"},
    )


def test_extract_from_chunk_accepts_valid_candidate():
    extractor = StubLLMExtractor(
        [
            (
                """
                [
                  {
                    "proposed_question_text": "What is the cancellation policy 60+ days before arrival?",
                    "proposed_answer_text": "Guests receive a full refund when cancelling 60+ days before arrival.",
                    "proposed_topic_id": "cancellation_policy",
                    "confidence": 0.92,
                    "evidence_excerpt": "Cancel 60+ days before arrival for a full refund.",
                    "uncertain": false,
                    "conditional": true,
                    "source_section": "Cancellation Policy"
                  }
                ]
                """,
                {"input_tokens": 100, "output_tokens": 50},
            )
        ]
    )

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.proposed_topic_id == "cancellation_policy"
    assert candidate.confidence == 0.92
    assert candidate.proposed_metadata["conditional"] is True
    assert result.usage is not None
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50


def test_extract_from_chunk_skips_invalid_topic_and_bad_evidence():
    extractor = StubLLMExtractor(
        [
            (
                """
                [
                  {
                    "proposed_question_text": "What is the policy?",
                    "proposed_answer_text": "A full refund is available.",
                    "proposed_topic_id": "made_up_topic",
                    "confidence": 0.91,
                    "evidence_excerpt": "A full refund is available.",
                    "uncertain": false,
                    "conditional": false,
                    "source_section": "Cancellation"
                  },
                  {
                    "proposed_question_text": "What happens under 30 days?",
                    "proposed_answer_text": "No refund is available.",
                    "proposed_topic_id": "cancellation_policy",
                    "confidence": 0.90,
                    "evidence_excerpt": "This sentence is not in the source.",
                    "uncertain": false,
                    "conditional": true,
                    "source_section": "Cancellation"
                  }
                ]
                """,
                {"input_tokens": 1, "output_tokens": 1},
            )
        ]
    )

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert result.candidates == []


def test_extract_from_chunk_handles_malformed_json():
    extractor = StubLLMExtractor([("not json", {"input_tokens": 1, "output_tokens": 1})])

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert result.candidates == []
    assert result.error is None


def test_extract_from_chunk_retries_request_errors():
    extractor = StubLLMExtractor(
        [
            httpx.RequestError("network", request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
            (
                """
                [
                  {
                    "proposed_question_text": "What is the cancellation policy 60+ days before arrival?",
                    "proposed_answer_text": "Guests receive a full refund when cancelling 60+ days before arrival.",
                    "proposed_topic_id": "cancellation_policy",
                    "confidence": 0.92,
                    "evidence_excerpt": "Cancel 60+ days before arrival for a full refund.",
                    "uncertain": false,
                    "conditional": true,
                    "source_section": "Cancellation Policy"
                  }
                ]
                """,
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ]
    )

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert len(result.candidates) == 1
    assert result.usage is not None
    assert result.usage.attempts == 2
    assert result.usage.retry_count == 1
    assert result.usage.retry_wait_time_seconds == 0.5


def test_batch_processing_aggregates_usage():
    extractor = StubLLMExtractor(
        [
            (
                """
                [
                  {
                    "proposed_question_text": "What is the cancellation policy 60+ days before arrival?",
                    "proposed_answer_text": "Guests receive a full refund when cancelling 60+ days before arrival.",
                    "proposed_topic_id": "cancellation_policy",
                    "confidence": 0.92,
                    "evidence_excerpt": "Cancel 60+ days before arrival for a full refund.",
                    "uncertain": false,
                    "conditional": true,
                    "source_section": "Cancellation Policy"
                  }
                ]
                """,
                {"input_tokens": 100, "output_tokens": 50},
            ),
            ("[]", {"input_tokens": 80, "output_tokens": 10}),
        ]
    )
    chunk_a = _chunk()
    chunk_b = ChunkedContent(
        chunk_id="chunk-2",
        source_block_hash="abc123def457",
        section_title="Parking",
        order_within_block=0,
        content_html="<p>Parking is available in the driveway.</p>",
        content_text="Parking is available in the driveway.",
        metadata={},
    )
    block_a = _canonical_block()
    block_b = CanonicalBlock(
        block_hash="abc123def457",
        render_type="home.about_note",
        tenant_id=TENANT_ID,
        canonical_source_property_id=PROPERTY_ID,
        canonical_page_id=3362,
        applicable_property_ids=[PROPERTY_ID],
        scope_type="property",
        duplicate_group_metadata=None,
        duplicate_count=1,
        block_content={"id": 100, "render_type": "home.about_note", "title": "Welcome", "page_title": "Welcome", "data": "<p>Parking is available in the driveway.</p>"},
    )

    result = asyncio.run(
        extractor.extract_from_chunks_batch(
            [chunk_a, chunk_b],
            {
                chunk_a.source_block_hash: block_a,
                chunk_b.source_block_hash: block_b,
            },
            concurrency=2,
        )
    )

    assert result.total_input_tokens == 180
    assert result.total_output_tokens == 60
    assert result.total_retry_count == 0
    assert result.total_retry_wait_time_seconds == 0.0
    assert result.failed_after_max_retries == 0
    assert result.failed_chunks == []
    assert len(result.results_by_chunk["chunk-1"]) == 1
    assert result.results_by_chunk["chunk-2"] == []


def test_extract_from_chunk_serializes_duplicate_group_uuid_metadata():
    extractor = StubLLMExtractor(
        [
            (
                """
                [
                  {
                    "proposed_question_text": "What is the trash pickup note?",
                    "proposed_answer_text": "Put trash out on Thursday night.",
                    "proposed_topic_id": null,
                    "confidence": 0.91,
                    "evidence_excerpt": "Put trash out on Thursday night.",
                    "uncertain": false,
                    "conditional": false,
                    "source_section": "Trash"
                  }
                ]
                """,
                {"input_tokens": 20, "output_tokens": 20},
            )
        ]
    )
    other_property_id = UUID("33333333-3333-3333-3333-333333333333")
    block = CanonicalBlock(
        block_hash="dup-group-hash",
        render_type="home.trash_info_note",
        tenant_id=TENANT_ID,
        canonical_source_property_id=PROPERTY_ID,
        canonical_page_id=4001,
        applicable_property_ids=[PROPERTY_ID, other_property_id],
        scope_type="property",
        duplicate_group_metadata={
            "group_id": "home_trash_info_note_abcd1234",
            "member_property_ids": [PROPERTY_ID, other_property_id],
            "member_count": 2,
            "block_hash": "dup-group-hash",
        },
        duplicate_count=2,
        block_content={
            "id": 101,
            "render_type": "home.trash_info_note",
            "title": "General",
            "page_title": "General",
            "data": "<p>Put trash out on Thursday night.</p>",
        },
    )
    chunk = ChunkedContent(
        chunk_id="chunk-trash-1",
        source_block_hash="dup-group-hash",
        section_title="Trash",
        order_within_block=0,
        content_html="<p>Put trash out on Thursday night.</p>",
        content_text="Put trash out on Thursday night.",
        metadata={},
    )

    result = asyncio.run(extractor.extract_from_chunk_detailed(chunk, block))

    assert len(result.candidates) == 1
    duplicate_group = result.candidates[0].proposed_metadata["duplicate_group_metadata"]
    assert duplicate_group["member_property_ids"] == [str(PROPERTY_ID), str(other_property_id)]


def test_extract_from_chunk_retries_429_with_retry_after_header():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        429,
        headers={"retry-after": "3"},
        json={"error": {"type": "rate_limit_error"}},
        request=request,
    )
    extractor = StubLLMExtractor(
        [
            httpx.HTTPStatusError("rate limited", request=request, response=response),
            (
                """
                [
                  {
                    "proposed_question_text": "What is the cancellation policy 60+ days before arrival?",
                    "proposed_answer_text": "Guests receive a full refund when cancelling 60+ days before arrival.",
                    "proposed_topic_id": "cancellation_policy",
                    "confidence": 0.92,
                    "evidence_excerpt": "Cancel 60+ days before arrival for a full refund.",
                    "uncertain": false,
                    "conditional": true,
                    "source_section": "Cancellation Policy"
                  }
                ]
                """,
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ]
    )

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert len(result.candidates) == 1
    assert extractor.sleep_calls == [3.0]
    assert result.usage is not None
    assert result.usage.retry_count == 1
    assert result.usage.retry_wait_time_seconds == 3.0
    assert result.usage.failed_after_max_retries is False


def test_extract_from_chunk_returns_failed_after_max_retries_for_429():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        429,
        json={"error": {"type": "rate_limit_error"}},
        request=request,
    )
    extractor = StubLLMExtractor(
        [
            httpx.HTTPStatusError("rate limited", request=request, response=response),
            httpx.HTTPStatusError("rate limited", request=request, response=response),
        ]
    )
    extractor._retry_attempts = 2
    extractor.jitter_value = 0.0

    result = asyncio.run(extractor.extract_from_chunk_detailed(_chunk(), _canonical_block()))

    assert result.candidates == []
    assert result.error == "http_429"
    assert extractor.sleep_calls == [2.0]
    assert result.usage is not None
    assert result.usage.retry_count == 1
    assert result.usage.failed_after_max_retries is True
