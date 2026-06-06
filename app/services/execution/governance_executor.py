"""
Execution: Governance Executor.

Thin wrapper around domain governance logic.
Translates DTOs/payloads → domain inputs → domain outputs.

Does NOT:
- Make decisions about what to run
- Handle retries/fallbacks
- Manage async concerns
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.domain.governance import (
    DecisionPolicy,
    PolicyDecision,
    PolicyRule,
    PolicyType,
    PolicyAction,
    EscalationLevel,
    HealthGrade,
    get_preset_policy,
    list_preset_names,
)


# =============================================================================
# PAYLOADS (DTOs for execution)
# =============================================================================

@dataclass
class PolicyEvaluationPayload:
    """Input for policy evaluation."""
    policy_name: str
    confidence: float
    health_grade: str  # HealthGrade value
    value: Optional[float] = None
    present_signals: Optional[List[str]] = None  # SignalType values
    extra_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluationResult:
    """Output from policy evaluation."""
    allowed: bool
    action: str
    reason: str
    matched_rule: Optional[str]
    escalation: str
    requires_audit: bool
    audit_reason: Optional[str]


@dataclass
class PolicySummary:
    """Summary of a policy configuration."""
    name: str
    description: str
    policy_type: str
    min_confidence: float
    min_health_grade: str
    rule_count: int
    is_active: bool


# =============================================================================
# GOVERNANCE EXECUTOR
# =============================================================================

class GovernanceExecutor:
    """
    Executes governance domain logic.
    
    Thin wrapper - translates DTOs to domain calls.
    No branching logic. No scheduling. No async.
    """
    
    def evaluate_policy(self, payload: PolicyEvaluationPayload) -> PolicyEvaluationResult:
        """Evaluate a decision against policy."""
        # Get the policy
        policy = get_preset_policy(payload.policy_name)
        
        # Build context
        context = {
            "confidence": payload.confidence,
            "health_grade": HealthGrade(payload.health_grade),
            "value": payload.value,
            **payload.extra_context,
        }
        
        # Add present signals if provided
        if payload.present_signals:
            context["present_signals"] = set(payload.present_signals)
        
        # Evaluate
        decision = policy.evaluate(context)
        
        return PolicyEvaluationResult(
            allowed=decision.is_allowed(),
            action=decision.action.value,
            reason=decision.reason,
            matched_rule=decision.matched_rule,
            escalation=decision.escalation.value,
            requires_audit=decision.requires_audit,
            audit_reason=decision.audit_reason,
        )
    
    def get_preset_names(self) -> List[str]:
        """Get list of available preset policy names."""
        return list_preset_names()
    
    def get_policy_summary(self, policy_name: str) -> PolicySummary:
        """Get summary of a policy."""
        policy = get_preset_policy(policy_name)
        
        return PolicySummary(
            name=policy.name,
            description=policy.description,
            policy_type=policy.policy_type.value,
            min_confidence=policy.min_confidence,
            min_health_grade=policy.min_health_grade.value,
            rule_count=len(policy.rules),
            is_active=policy.is_active,
        )
    
    def list_policies(self) -> List[PolicySummary]:
        """List all available policies with summaries."""
        return [
            self.get_policy_summary(name)
            for name in self.get_preset_names()
        ]
    
    def check_automation_allowed(
        self, 
        policy_name: str, 
        confidence: float
    ) -> bool:
        """Check if automation is allowed under a policy at given confidence."""
        policy = get_preset_policy(policy_name)
        return (
            policy.allow_automation and 
            confidence >= policy.automation_confidence_threshold
        )


# =============================================================================
# SINGLETON
# =============================================================================

_executor: Optional[GovernanceExecutor] = None


def get_governance_executor() -> GovernanceExecutor:
    """Get governance executor singleton."""
    global _executor
    if _executor is None:
        _executor = GovernanceExecutor()
    return _executor


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Payloads
    "PolicyEvaluationPayload",
    "PolicyEvaluationResult",
    "PolicySummary",
    
    # Executor
    "GovernanceExecutor",
    "get_governance_executor",
]
