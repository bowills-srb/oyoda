from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging.autonomy_gate import AutonomyDecision, GateResult
from app.services.messaging.identity_resolver import GuestIdentityResolution
from app.services.messaging_brain.agents.response_policy_agent import ResponsePolicyAgent
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)


def _message(identity: GuestIdentityResolution | None) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="msg-1",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text="hello",
        guest_name="Jordan",
        identity=identity,
        property_id=str(uuid4()),
        property_code="SUNSET_1",
        lifecycle=MessagingLifecycle.IN_STAY,
    )


def _context() -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_id=str(uuid4()),
        property_code="SUNSET_1",
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts={},
        property_knowledge={},
        guidebook_knowledge={},
        guidebook_richness={},
        guidebook_evidence=[],
        learned_preferences_block="",
        operator_policies={},
        operator_guidance="",
        reservation_facts={},
        house_rules={},
        access_info={},
        maintenance_status={},
        local_guidebook_facts={},
        market_signals={},
        prior_guest_messages=[],
        operator_commitments=[],
        evidence_keys=[],
        missing_context=[],
    )


def _decision(*, confidence: float = 0.95) -> AgentDecision:
    return AgentDecision(
        agent_name="GeneralAgent",
        intent_topic="general",
        confidence=confidence,
        answer_summary="ok",
        recommended_action=RecommendedAction.AUTO_SEND,
    )


@pytest.mark.asyncio
async def test_policy_downgrades_pseudonymous_auto_send_to_review():
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=AsyncMock(
            return_value=GateResult(
                decision=AutonomyDecision.AUTO_SEND,
                reason="high confidence",
                approval_mode_at_decision="auto",
            )
        ),
    ):
        result = await agent.evaluate(
            message=_message(
                GuestIdentityResolution(
                    state="pseudonymous",
                    guest_email="abc123@messages.vrbo.com",
                    resolution_source="ota_masked_email",
                    confidence=0.55,
                )
            ),
            context=_context(),
            decisions=[_decision()],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.DRAFT_ONLY
    assert any("pseudonymous" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_policy_escalates_anonymous_without_calling_autonomy_gate():
    agent = ResponsePolicyAgent()
    gate = AsyncMock()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=gate,
    ):
        result = await agent.evaluate(
            message=_message(GuestIdentityResolution(state="anonymous")),
            context=_context(),
            decisions=[_decision()],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE
    gate.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_downgrades_identified_auto_send_below_threshold():
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=AsyncMock(
            return_value=GateResult(
                decision=AutonomyDecision.AUTO_SEND,
                reason="high confidence",
                approval_mode_at_decision="auto",
            )
        ),
    ):
        result = await agent.evaluate(
            message=_message(
                GuestIdentityResolution(
                    state="identified",
                    reservation_id="res-1",
                    session_token="gh_123",
                    resolution_source="session_token",
                    confidence=0.99,
                )
            ),
            context=_context(),
            decisions=[_decision(confidence=0.95)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.DRAFT_ONLY
    assert any("effective autonomy threshold" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_policy_keeps_identified_auto_send_at_threshold():
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=AsyncMock(
            return_value=GateResult(
                decision=AutonomyDecision.AUTO_SEND,
                reason="perfect confidence",
                approval_mode_at_decision="auto",
            )
        ),
    ):
        result = await agent.evaluate(
            message=_message(
                GuestIdentityResolution(
                    state="identified",
                    reservation_id="res-1",
                    session_token="gh_123",
                    resolution_source="session_token",
                    confidence=0.99,
                )
            ),
            context=_context(),
            decisions=[_decision(confidence=1.0)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.AUTO_SEND
