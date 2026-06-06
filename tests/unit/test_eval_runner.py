"""
test_eval_runner.py — Unit tests for eval_runner.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

import pytest
import pytest_asyncio

import app.services.messaging_brain.eval.eval_runner as eval_runner_module
from app.services.messaging_brain.eval.eval_case_store import upsert_case
from app.services.messaging_brain.eval.eval_runner import format_run_report, run_eval
from app.services.orchestration.messaging_brain_contracts import (
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


class MockKeywordClassifier:
    name = "IntakeAgent"

    def __init__(self, *, intent_topic: str = "general"):
        self._intent_topic = intent_topic

    async def classify(self, message: InboundGuestMessage, *, db_session=None):
        return MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic=self._intent_topic,
            confidence=0.6,
            urgency=Urgency.MEDIUM,
        )


class MockLLMClassifier:
    name = "IntakeAgent"

    def __init__(
        self,
        *,
        intent_topic: str = "booking_inquiry",
        sub_intents: Optional[List[str]] = None,
        constraints: Optional[dict] = None,
        provider: str = "anthropic",
    ):
        self._intent_topic = intent_topic
        self._sub_intents = sub_intents or []
        self._constraints = constraints or {}
        self._provider = provider

    async def classify(self, message, *, db_session=None):
        cls, _ = await self.classify_with_metadata(message, db_session=db_session)
        return cls

    async def classify_with_metadata(self, message, *, db_session=None):
        cls = MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic=self._intent_topic,
            sub_intents=self._sub_intents,
            extracted_constraints=self._constraints,
            confidence=0.85,
            urgency=Urgency.MEDIUM,
        )
        meta = ClassifierMetadata(
            classifier_source="llm",
            provider_used=self._provider,
            latency_ms=42,
        )
        return cls, meta


@pytest_asyncio.fixture
async def seeded_db(stub_db):
    await upsert_case(
        stub_db,
        case_key="coastal_a",
        message_text="Q1",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    await upsert_case(
        stub_db,
        case_key="coastal_b",
        message_text="Q2",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="general",
        expected_review=True,
    )
    await upsert_case(
        stub_db,
        case_key="ski_a",
        message_text="Q3",
        market_tag="breckenridge_ski",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    yield stub_db


@pytest.mark.asyncio
async def test_run_eval_with_classifier_that_passes_all_cases(seeded_db):
    db = seeded_db

    class AllPassClassifier:
        name = "IntakeAgent"

        async def classify(self, message, *, db_session=None):
            key = message.message_id.replace("eval_", "")
            if key == "coastal_b":
                return MessageClassification(
                    intent_type=IntentType.QUESTION,
                    intent_topic="general",
                    confidence=0.7,
                    urgency=Urgency.MEDIUM,
                    requires_human_review=True,
                )
            return MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="booking_inquiry",
                confidence=0.85,
                urgency=Urgency.MEDIUM,
                requires_human_review=False,
            )

    result = await run_eval(
        db=db,
        classifier=AllPassClassifier(),
        classifier_source="keyword",
    )
    assert result.cases_evaluated == 3
    assert result.cases_passed == 3
    assert result.cases_failed == 0
    assert result.accuracy_overall == 1.0
    assert result.accuracy_by_market == {
        "coastal_30a": 1.0,
        "breckenridge_ski": 1.0,
    }
    assert result.run_id is not None


@pytest.mark.asyncio
async def test_run_eval_with_mixed_pass_fail(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
    )
    assert result.cases_evaluated == 3
    assert result.cases_passed == 0
    assert result.cases_failed == 3


@pytest.mark.asyncio
async def test_run_eval_market_filter_narrows(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        market_filter="coastal_30a",
    )
    assert result.cases_evaluated == 2
    case_keys = {r.case.case_key for r in result.case_results}
    assert case_keys == {"coastal_a", "coastal_b"}


@pytest.mark.asyncio
async def test_run_eval_case_keys_filter(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        case_keys=["ski_a"],
    )
    assert result.cases_evaluated == 1
    assert result.case_results[0].case.case_key == "ski_a"


@pytest.mark.asyncio
async def test_run_eval_empty_case_set_returns_without_writing(stub_db):
    result = await run_eval(
        db=stub_db,
        classifier=MockKeywordClassifier(),
        classifier_source="keyword",
        market_filter="nonexistent_market",
    )
    assert result.cases_evaluated == 0
    assert result.run_id is None
    assert len(stub_db.runs) == 0


@pytest.mark.asyncio
async def test_dry_run_does_not_write_run_header(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        dry_run=True,
    )
    assert result.dry_run is True
    assert result.run_id is None
    assert len(seeded_db.runs) == 0


@pytest.mark.asyncio
async def test_dry_run_does_not_write_run_cases(seeded_db):
    await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        dry_run=True,
    )
    assert len(seeded_db.run_cases) == 0


@pytest.mark.asyncio
async def test_dry_run_still_returns_per_case_results(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        dry_run=True,
    )
    assert len(result.case_results) == 3


@pytest.mark.asyncio
async def test_llm_path_populates_classifier_provider(seeded_db):
    await run_eval(
        db=seeded_db,
        classifier=MockLLMClassifier(
            intent_topic="booking_inquiry",
            sub_intents=[],
            provider="anthropic",
        ),
        classifier_source="llm",
    )
    for run_case in seeded_db.run_cases.values():
        assert run_case["classifier_provider"] == "anthropic"


@pytest.mark.asyncio
async def test_keyword_path_does_not_populate_provider(seeded_db):
    await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="booking_inquiry"),
        classifier_source="keyword",
    )
    for run_case in seeded_db.run_cases.values():
        assert run_case["classifier_provider"] is None


@pytest.mark.asyncio
async def test_run_records_latency_ms(seeded_db):
    await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="booking_inquiry"),
        classifier_source="keyword",
    )
    for run_case in seeded_db.run_cases.values():
        assert run_case["latency_ms"] is not None
        assert run_case["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_explicit_invocation_id_used_when_provided(seeded_db):
    explicit = str(uuid.uuid4())
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(),
        classifier_source="keyword",
        invocation_id=explicit,
    )
    assert result.invocation_id == explicit
    assert seeded_db.runs[result.run_id]["invocation_id"] == explicit


@pytest.mark.asyncio
async def test_two_runs_same_invocation_id_pairs_them(seeded_db):
    invocation = str(uuid.uuid4())
    result1 = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
        invocation_id=invocation,
    )
    result2 = await run_eval(
        db=seeded_db,
        classifier=MockLLMClassifier(intent_topic="booking_inquiry"),
        classifier_source="llm",
        invocation_id=invocation,
    )
    assert result1.invocation_id == invocation
    assert result2.invocation_id == invocation
    assert result1.run_id != result2.run_id
    assert (
        seeded_db.runs[result1.run_id]["invocation_id"]
        == seeded_db.runs[result2.run_id]["invocation_id"]
    )


@pytest.mark.asyncio
async def test_invalid_classifier_source_raises(stub_db):
    with pytest.raises(ValueError, match="classifier_source must be"):
        await run_eval(
            db=stub_db,
            classifier=MockKeywordClassifier(),
            classifier_source="invalid_value",
        )


@pytest.mark.asyncio
async def test_format_run_report_includes_classifier_and_accuracy(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
    )
    report = format_run_report(result)
    assert "keyword" in report
    assert "Cases evaluated:" in report
    assert "Per-market accuracy:" in report
    assert "coastal_30a" in report
    assert "breckenridge_ski" in report


@pytest.mark.asyncio
async def test_format_run_report_lists_failures(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(intent_topic="general"),
        classifier_source="keyword",
    )
    report = format_run_report(result)
    assert "Failures:" in report
    assert "coastal_a" in report


@pytest.mark.asyncio
async def test_format_dry_run_marks_dry(seeded_db):
    result = await run_eval(
        db=seeded_db,
        classifier=MockKeywordClassifier(),
        classifier_source="keyword",
        dry_run=True,
    )
    report = format_run_report(result)
    assert "dry run" in report.lower()


@pytest.mark.asyncio
async def test_keyword_classifier_skips_sub_intent_check(stub_db):
    await upsert_case(
        stub_db,
        case_key="sub_intent_case",
        message_text="Q",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_sub_intents=["pricing"],
        expected_review=False,
    )
    result = await run_eval(
        db=stub_db,
        classifier=MockKeywordClassifier(intent_topic="booking_inquiry"),
        classifier_source="keyword",
    )
    assert result.cases_passed == 1


@pytest.mark.asyncio
async def test_llm_classifier_enforces_sub_intent_check(stub_db):
    await upsert_case(
        stub_db,
        case_key="sub_intent_case",
        message_text="Q",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_sub_intents=["pricing"],
        expected_review=False,
    )
    result = await run_eval(
        db=stub_db,
        classifier=MockLLMClassifier(intent_topic="booking_inquiry", sub_intents=[]),
        classifier_source="llm",
    )
    assert result.cases_passed == 0
    assert result.cases_failed == 1


class _DBSessionRecordingKeywordClassifier:
    name = "IntakeAgent"

    def __init__(self):
        self.received_sessions: List[Any] = []

    async def classify(self, message, *, db_session=None):
        self.received_sessions.append(db_session)
        return MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="booking_inquiry",
            confidence=0.7,
            urgency=Urgency.MEDIUM,
        )


class _DBSessionRecordingLLMClassifier:
    name = "IntakeAgent"

    def __init__(self):
        self.received_sessions: List[Any] = []

    async def classify(self, message, *, db_session=None):
        cls, _ = await self.classify_with_metadata(message, db_session=db_session)
        return cls

    async def classify_with_metadata(self, message, *, db_session=None):
        self.received_sessions.append(db_session)
        cls = MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="booking_inquiry",
            confidence=0.85,
            urgency=Urgency.MEDIUM,
        )
        meta = ClassifierMetadata(
            classifier_source="llm",
            provider_used="anthropic",
            latency_ms=10,
        )
        return cls, meta


@pytest.mark.asyncio
async def test_runner_propagates_db_session_to_keyword_classifier(seeded_db):
    classifier = _DBSessionRecordingKeywordClassifier()
    await run_eval(
        db=seeded_db,
        classifier=classifier,
        classifier_source="keyword",
    )
    assert len(classifier.received_sessions) == 3
    for session in classifier.received_sessions:
        assert session is seeded_db


@pytest.mark.asyncio
async def test_runner_propagates_db_session_to_llm_classifier(seeded_db):
    classifier = _DBSessionRecordingLLMClassifier()
    await run_eval(
        db=seeded_db,
        classifier=classifier,
        classifier_source="llm",
    )
    assert len(classifier.received_sessions) == 3
    for session in classifier.received_sessions:
        assert session is seeded_db


@pytest.mark.asyncio
async def test_finish_run_failure_marks_run_failed(seeded_db, monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("aggregate write blew up")

    monkeypatch.setattr(eval_runner_module, "finish_run", _boom)

    with pytest.raises(RuntimeError, match="aggregate write blew up"):
        await run_eval(
            db=seeded_db,
            classifier=MockKeywordClassifier(intent_topic="booking_inquiry"),
            classifier_source="keyword",
        )

    assert len(seeded_db.runs) == 1
    run = next(iter(seeded_db.runs.values()))
    assert run["status"] == "failed"
    assert run["run_completed_at"] is not None
    assert "finish_run_failed: RuntimeError: aggregate write blew up" in (
        run["notes"] or ""
    )
