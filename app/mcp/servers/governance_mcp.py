"""
Governance MCP Server

Wraps app/services/governance/decision_policies.py and
app/services/signals/signal_contract.py (ConfidenceThresholds).

This is "Lock 1" and "Lock 3" of the Three-Lock system:
  Lock 1: Financial Picket — agents cannot charge >$100 without HITL
  Lock 3: Truth Anchor — agents cannot confirm availability if confidence < threshold

Tools exposed:
  evaluate_policy(policy_name, confidence, value)  → PolicyDecision
  check_financial_gate(amount_usd)                 → bool + requires_human
  check_truth_anchor(geo_id, output_type)           → bool + hedge_language
  get_audit_log(limit)                              → recent policy decisions
  list_policies()                                   → available policy names
"""

import logging
from typing import Any, Dict, List

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)

# Financial thresholds — hard-coded, not config, so agents can't override them
FINANCIAL_GATE_USD = 100.0      # HITL required above this
AUTO_APPROVE_USD = 25.0         # Auto-approve below this


class GovernanceMCPServer(MCPServer):
    """In-process access to the Governance / Policy engine."""

    server_name = "governance"
    server_description = "Decision policies, financial gates, truth anchors, audit log"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="evaluate_policy",
                description="Evaluate a named decision policy against a context",
                parameters={
                    "type": "object",
                    "properties": {
                        "policy_name": {
                            "type": "string",
                            "enum": [
                                "high_confidence_pricing", "standard_discount",
                                "voice_conservative", "institutional_investment",
                            ],
                        },
                        "confidence": {"type": "number"},
                        "health_grade": {
                            "type": "string",
                            "enum": ["A", "B", "C", "D", "F"],
                            "default": "C",
                        },
                        "value": {"type": "number", "description": "The value being evaluated (e.g. discount %)"},
                    },
                    "required": ["policy_name", "confidence"],
                },
                returns="PolicyDecision: {allowed, action, reason, needs_escalation, matched_rule}",
                category="governance",
            ),
            MCPTool(
                name="check_financial_gate",
                description="Lock 1: Can the agent proceed with a financial action of this amount?",
                parameters={
                    "type": "object",
                    "properties": {
                        "amount_usd": {"type": "number"},
                        "action_type": {
                            "type": "string",
                            "enum": ["refund", "discount", "coupon", "reservation", "charge"],
                        },
                    },
                    "required": ["amount_usd", "action_type"],
                },
                returns="Dict: {proceed: bool, requires_human: bool, reason: str, gate_threshold: float}",
                category="governance",
            ),
            MCPTool(
                name="check_truth_anchor",
                description="Lock 3: Is the agent allowed to make a definitive claim about this?",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "output_type": {
                            "type": "string",
                            "enum": [
                                "voice_pricing", "voice_discount", "voice_market",
                                "availability_confirm", "rate_quote",
                            ],
                        },
                    },
                    "required": ["geo_id", "output_type"],
                },
                returns="Dict: {may_assert: bool, hedge_language: str, confidence: float}",
                category="governance",
            ),
            MCPTool(
                name="list_policies",
                description="List all available policy names and their types",
                parameters={"type": "object", "properties": {}, "required": []},
                returns="List of {name, type, description} dicts",
                category="governance",
            ),
            MCPTool(
                name="get_audit_log",
                description="Get recent policy decisions from the audit log",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": [],
                },
                returns="List of audit log entries",
                category="governance",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "evaluate_policy":
            return self._evaluate_policy(operator_id, params)
        elif tool_name == "check_financial_gate":
            return self._check_financial_gate(operator_id, params)
        elif tool_name == "check_truth_anchor":
            return await self._check_truth_anchor(operator_id, params)
        elif tool_name == "list_policies":
            return self._list_policies(operator_id, params)
        elif tool_name == "get_audit_log":
            return self._get_audit_log(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    def _evaluate_policy(self, operator_id: str, params: Dict) -> MCPResult:
        try:
            from app.services.governance.decision_policies import evaluate_policy
            from app.services.health.signal_health import HealthGrade

            grade_map = {"A": HealthGrade.A, "B": HealthGrade.B, "C": HealthGrade.C,
                         "D": HealthGrade.D, "F": HealthGrade.F}
            health_grade = grade_map.get(params.get("health_grade", "C"), HealthGrade.C)

            decision = evaluate_policy(
                policy_name=params["policy_name"],
                confidence=params["confidence"],
                health_grade=health_grade,
                value=params.get("value"),
            )

            return MCPResult(
                success=True,
                data={
                    "allowed": decision.is_allowed(),
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "needs_escalation": decision.needs_escalation(),
                    "escalation_level": decision.escalation.value,
                    "matched_rule": decision.matched_rule,
                    "requires_audit": decision.requires_audit,
                },
                message=f"Policy {params['policy_name']}: {'ALLOW' if decision.is_allowed() else 'GATE/DENY'}",
            )
        except Exception as e:
            return MCPResult(success=False, message=str(e))

    def _check_financial_gate(self, operator_id: str, params: Dict) -> MCPResult:
        amount = params["amount_usd"]
        action_type = params["action_type"]

        if amount <= AUTO_APPROVE_USD:
            return MCPResult(
                success=True,
                data={
                    "proceed": True,
                    "requires_human": False,
                    "reason": f"Amount ${amount:.2f} is below auto-approve threshold ${AUTO_APPROVE_USD}",
                    "gate_threshold": FINANCIAL_GATE_USD,
                },
                message=f"PROCEED: ${amount:.2f} {action_type} — below threshold",
            )
        elif amount <= FINANCIAL_GATE_USD:
            return MCPResult(
                success=True,
                data={
                    "proceed": True,
                    "requires_human": False,
                    "reason": f"Amount ${amount:.2f} is within agent authority (max ${FINANCIAL_GATE_USD})",
                    "gate_threshold": FINANCIAL_GATE_USD,
                },
                message=f"PROCEED: ${amount:.2f} {action_type} — within authority",
            )
        else:
            return MCPResult(
                success=True,
                data={
                    "proceed": False,
                    "requires_human": True,
                    "reason": f"Amount ${amount:.2f} exceeds agent limit of ${FINANCIAL_GATE_USD}. Requires HITL approval.",
                    "gate_threshold": FINANCIAL_GATE_USD,
                },
                message=f"GATE: ${amount:.2f} {action_type} — requires human approval",
            )

    async def _check_truth_anchor(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        output_type = params["output_type"]

        # Map output_type to confidence threshold type
        type_map = {
            "voice_pricing": "voice_pricing",
            "voice_discount": "voice_discount",
            "voice_market": "voice_market",
            "availability_confirm": "voice_market",
            "rate_quote": "voice_pricing",
        }
        threshold_type = type_map.get(output_type, "internal")

        try:
            from app.services.signals.signal_pipeline import SignalPipeline
            from app.services.signals.signal_contract import is_confidence_sufficient

            pipeline = SignalPipeline()
            bundle = await pipeline.get_signal_bundle(geo_id)
            confidence = bundle.get("overall_confidence", 0.0)
        except Exception:
            confidence = 0.0

        may_assert = confidence >= 0.65  # Direct threshold check

        # Hedge language for when assertion is not allowed
        hedge_language = (
            "" if may_assert else
            "I want to make sure I give you accurate information — let me double-check that with the property details and get right back to you."
        )

        return MCPResult(
            success=True,
            data={
                "may_assert": may_assert,
                "confidence": confidence,
                "output_type": output_type,
                "geo_id": geo_id,
                "hedge_language": hedge_language,
            },
            message=f"Truth anchor: {'ASSERT ALLOWED' if may_assert else 'MUST HEDGE'} ({confidence:.2f})",
        )

    def _list_policies(self, operator_id: str, params: Dict) -> MCPResult:
        try:
            from app.services.governance.decision_policies import get_policy_service
            service = get_policy_service()
            policies = [
                {
                    "name": name,
                    "type": p.policy_type.value,
                    "min_confidence": p.min_confidence,
                    "description": p.description,
                }
                for name, p in service._policies.items()
            ]
            return MCPResult(success=True, data={"policies": policies}, message=f"{len(policies)} policies available")
        except Exception as e:
            return MCPResult(success=False, message=str(e))

    def _get_audit_log(self, operator_id: str, params: Dict) -> MCPResult:
        limit = params.get("limit", 20)
        try:
            from app.services.governance.decision_policies import get_policy_service
            service = get_policy_service()
            log = service.get_audit_log(limit=limit)
            return MCPResult(success=True, data={"entries": log, "count": len(log)}, message=f"{len(log)} audit entries")
        except Exception as e:
            return MCPResult(success=False, message=str(e))
