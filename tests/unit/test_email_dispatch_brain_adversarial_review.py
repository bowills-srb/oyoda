from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.integrations.email_dispatch import (
    _review_brain_pre_booking_draft,
)


def _review_result(
    *,
    verdict: str,
    reviewed_response: str = "",
    rationale: str = "reason",
    flags: list[str] | None = None,
    review_source: str = "heuristic+anthropic_adversarial",
):
    return SimpleNamespace(
        verdict=verdict,
        reviewed_response=reviewed_response,
        rationale=rationale,
        flags=flags or [],
        review_source=review_source,
    )


@pytest.mark.asyncio
async def test_review_brain_pre_booking_draft_approve_keeps_original(monkeypatch):
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(return_value=_review_result(verdict="approve")),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="Is the pool heated?",
        intent="amenities",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Yes, the pool can be heated for your stay.",
        tenant_id=None,
    )

    assert final_text == "Yes, the pool can be heated for your stay."
    assert flags == []
    assert verdict == "pass"
    assert len(warnings) == 1
    assert "verdict=approve" in warnings[0]
    assert "revised=false" in warnings[0]


@pytest.mark.asyncio
async def test_review_brain_pre_booking_draft_revise_uses_reviewed_text(monkeypatch):
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(
            return_value=_review_result(
                verdict="revise",
                reviewed_response="I'll confirm whether pool heating is available and follow up shortly.",
                rationale="softened unsupported certainty",
                flags=["ungrounded_amenity_fact"],
            )
        ),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="Is the pool heated?",
        intent="amenities",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Yes, the pool is heated year-round.",
        tenant_id=None,
    )

    assert final_text == "I'll confirm whether pool heating is available and follow up shortly."
    assert flags == ["ℹ️ Adversarial review revised the brain draft before operator display"]
    assert verdict == "revise"
    assert "verdict=revise" in warnings[0]
    assert "revised=true" in warnings[0]


@pytest.mark.asyncio
async def test_review_brain_pre_booking_draft_human_review_returns_empty_text_and_hold_verdict(monkeypatch):
    """Commit 2C-flip behavior: when the reviewer holds the draft, the
    returned final_text is the empty string. Persistence and the alert
    SMS branch on verdict='hold' rather than on text content, which means
    operators see an explicit "AI declined to draft" message instead of
    fallback boilerplate that reads like a confident draft.
    """
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(
            return_value=_review_result(
                verdict="human_review",
                rationale="missing pool-heating grounding",
                flags=["ungrounded_amenity_fact"],
            )
        ),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="Is the pool heated?",
        intent="amenities",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Yes, the pool is heated year-round.",
        tenant_id=None,
    )

    assert final_text == ""
    assert flags == ["ℹ️ Adversarial review forced operator hold (human_review)"]
    assert verdict == "hold"
    assert "verdict=human_review" in warnings[0]
    assert "revised=true" in warnings[0]


@pytest.mark.asyncio
async def test_review_brain_pre_booking_draft_block_returns_empty_text_and_hold_verdict(monkeypatch):
    """Same as human_review: a 'block' verdict also empties the text and
    tags hold. Both verdicts route to the same persistence treatment.
    """
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(
            return_value=_review_result(
                verdict="block",
                rationale="policy violation",
                flags=["policy_violation"],
            )
        ),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="Can I get a 50% discount?",
        intent="pricing",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Sure, I can offer you 50% off!",
        tenant_id=None,
    )

    assert final_text == ""
    assert verdict == "hold"
    assert "ℹ️ Adversarial review forced operator hold (block)" in flags


@pytest.mark.asyncio
async def test_defensive_guard_catches_residual_placeholder_in_draft_text(monkeypatch):
    """The placeholder guard is a separate code path from the reviewer-hold
    substitution. It still uses _fallback_draft because the trigger is
    different (the brain emitted a literal placeholder like '[insert
    door code]') and the right response is a graceful fallback, not an
    empty held-by-review signal.
    """
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking._fallback_draft",
        lambda *args, **kwargs: "Thanks for reaching out — a teammate will follow up with the exact details.",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(return_value=_review_result(verdict="approve")),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="What's the door code?",
        intent="check_in_process",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Your check-in code is [insert door code here].",
        tenant_id=None,
    )

    assert final_text == "Thanks for reaching out — a teammate will follow up with the exact details."
    assert "ℹ️ Defensive placeholder guard caught residual placeholder text" in flags
    assert verdict == "pass"
    assert any("defensive_placeholder_guard:source=draft" in w for w in warnings)
    assert any("matched=" in w for w in warnings)
    assert any("verdict=approve" in w for w in warnings)


@pytest.mark.asyncio
async def test_defensive_guard_inert_on_clean_draft_and_final(monkeypatch):
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(return_value=_review_result(verdict="approve")),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="Is the pool heated?",
        intent="amenities",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Yes, the pool can be heated for your stay.",
        tenant_id=None,
    )

    assert final_text == "Yes, the pool can be heated for your stay."
    assert "ℹ️ Defensive placeholder guard caught residual placeholder text" not in flags
    assert verdict == "pass"
    assert not any("defensive_placeholder_guard:" in w for w in warnings)
    assert any("verdict=approve" in w for w in warnings)


@pytest.mark.asyncio
async def test_defensive_guard_engages_when_verdict_already_held(monkeypatch):
    """When the reviewer holds AND the original draft contains a placeholder,
    both signals are recorded:
      - verdict is 'hold' and final_text is '' (from the reviewer-hold branch)
      - the placeholder guard fires on the original draft_text and records
        the flag/warning
    The guard does NOT substitute _fallback_draft into final_text here
    because the substitution branch requires `final_placeholder_match` to
    be truthy, and an empty final_text won't match any placeholder pattern.
    The hold semantics win.
    """
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        lambda **kwargs: "guest_name: Taylor\nplatform: vrbo",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking._fallback_draft",
        lambda *args, **kwargs: "Thanks for reaching out — a teammate will follow up.",
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        AsyncMock(
            return_value=_review_result(
                verdict="human_review",
                rationale="missing context",
                flags=["ungrounded_amenity_fact"],
            )
        ),
    )

    final_text, flags, warnings, verdict = await _review_brain_pre_booking_draft(
        guest_name="Taylor",
        platform="vrbo",
        message="What's the door code?",
        intent="check_in_process",
        property_data={"property_name": "Gulf View 204"},
        operator_policies={},
        draft_text="Your check-in code is [insert door code here].",
        tenant_id=None,
    )

    assert verdict == "hold"
    assert final_text == ""
    assert "ℹ️ Defensive placeholder guard caught residual placeholder text" in flags
    assert any("defensive_placeholder_guard:source=draft" in w for w in warnings)
    assert "ℹ️ Adversarial review forced operator hold (human_review)" in flags
