"""
Domain: Governance - Pure Policy Models.

No FastAPI. No DB sessions. No external API calls.
Pure business rules for decision governance.

Policies define:
- Confidence thresholds
- Allowed actions
- Gating rules
- Audit requirements
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4


# =============================================================================
# POLICY ENUMS
# =============================================================================

class PolicyType(str, Enum):
    """Types of decision policies."""
    PRICING = "pricing"
    DISCOUNT = "discount"
    VOICE = "voice"
    INVESTMENT = "investment"
    EXPANSION = "expansion"
    AUTOMATION = "automation"


class PolicyAction(str, Enum):
    """Actions a policy can control."""
    ALLOW = "allow"
    DENY = "deny"
    GATE = "gate"
    ESCALATE = "escalate"
    AUDIT = "audit"


class EscalationLevel(str, Enum):
    """Escalation levels."""
    NONE = "none"
    MANAGER = "manager"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


class HealthGrade(str, Enum):
    """Signal health grades."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


GRADE_ORDER = [HealthGrade.F, HealthGrade.D, HealthGrade.C, HealthGrade.B, HealthGrade.A]


def grade_to_rank(grade: HealthGrade) -> int:
    """Convert grade to numeric rank for comparison."""
    return GRADE_ORDER.index(grade)


def compare_grades(grade1: HealthGrade, grade2: HealthGrade) -> int:
    """Compare grades. Returns -1 if grade1 < grade2, 0 if equal, 1 if greater."""
    r1, r2 = grade_to_rank(grade1), grade_to_rank(grade2)
    if r1 < r2:
        return -1
    elif r1 > r2:
        return 1
    return 0


# =============================================================================
# POLICY RULE
# =============================================================================

@dataclass
class PolicyRule:
    """
    A single rule within a policy.
    
    Rules are evaluated in order; first match wins.
    Pure domain object - evaluates conditions against context.
    """
    name: str
    description: str
    
    # Conditions
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    min_health_grade: Optional[HealthGrade] = None
    required_signal_types: Optional[Set[str]] = None  # SignalType values
    
    # Thresholds
    max_value: Optional[float] = None
    min_value: Optional[float] = None
    
    # Action
    action: PolicyAction = PolicyAction.ALLOW
    escalation: EscalationLevel = EscalationLevel.NONE
    
    # Audit
    requires_audit: bool = False
    audit_reason: Optional[str] = None
    
    def evaluate(self, context: Dict[str, Any]) -> bool:
        """
        Evaluate if this rule matches the context.
        
        Returns True if rule matches (and should be applied).
        """
        # Check confidence bounds
        confidence = context.get("confidence", 0)
        if self.min_confidence is not None and confidence < self.min_confidence:
            return False
        if self.max_confidence is not None and confidence > self.max_confidence:
            return False
        
        # Check health grade
        if self.min_health_grade is not None:
            grade = context.get("health_grade")
            if grade and compare_grades(grade, self.min_health_grade) < 0:
                return False
        
        # Check required signals
        if self.required_signal_types:
            present = context.get("present_signals", set())
            if not self.required_signal_types.issubset(present):
                return False
        
        # Check value thresholds
        value = context.get("value")
        if value is not None:
            if self.max_value is not None and value > self.max_value:
                return False
            if self.min_value is not None and value < self.min_value:
                return False
        
        return True


# =============================================================================
# POLICY DECISION (Output)
# =============================================================================

@dataclass
class PolicyDecision:
    """
    Result of policy evaluation.
    
    This is the audit trail for every decision.
    Pure output object.
    """
    policy_id: UUID
    policy_name: str
    
    # Decision
    action: PolicyAction
    reason: str
    matched_rule: Optional[str]
    
    # Escalation
    escalation: EscalationLevel
    
    # Audit
    requires_audit: bool
    audit_reason: Optional[str] = None
    
    # Timestamp
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def is_allowed(self) -> bool:
        """Check if decision allows the action."""
        return self.action == PolicyAction.ALLOW
    
    def is_denied(self) -> bool:
        """Check if decision denies the action."""
        return self.action == PolicyAction.DENY
    
    def is_gated(self) -> bool:
        """Check if decision gates the action."""
        return self.action == PolicyAction.GATE
    
    def needs_escalation(self) -> bool:
        """Check if decision requires escalation."""
        return self.action == PolicyAction.ESCALATE or self.escalation != EscalationLevel.NONE
    
    def to_audit_record(self) -> Dict[str, Any]:
        """Convert to audit record."""
        return {
            "policy_id": str(self.policy_id),
            "policy_name": self.policy_name,
            "action": self.action.value,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "escalation": self.escalation.value,
            "requires_audit": self.requires_audit,
            "audit_reason": self.audit_reason,
            "decided_at": self.decided_at.isoformat(),
        }


# =============================================================================
# DECISION POLICY
# =============================================================================

@dataclass
class DecisionPolicy:
    """
    A complete decision policy.
    
    Policies are versioned, auditable configurations that control
    how the system makes decisions. Pure domain object.
    """
    id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    policy_type: PolicyType = PolicyType.PRICING
    
    # Version for audit trail
    version: str = "1.0.0"
    
    # Rules (evaluated in order)
    rules: List[PolicyRule] = field(default_factory=list)
    
    # Default action if no rules match
    default_action: PolicyAction = PolicyAction.GATE
    default_escalation: EscalationLevel = EscalationLevel.MANAGER
    
    # Global thresholds
    min_confidence: float = 0.5
    min_health_grade: HealthGrade = HealthGrade.C
    
    # Operator limits
    max_operator_delta: float = 0.15
    max_discount: float = 0.30
    
    # Automation controls
    allow_automation: bool = True
    automation_confidence_threshold: float = 0.75
    
    # Audit settings
    audit_all_decisions: bool = False
    audit_denied_decisions: bool = True
    audit_escalated_decisions: bool = True
    
    # Active status
    is_active: bool = True
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    
    def evaluate(self, context: Dict[str, Any]) -> PolicyDecision:
        """
        Evaluate policy against context.
        
        Returns PolicyDecision with action and audit trail.
        Pure function - context in, decision out.
        """
        confidence = context.get("confidence", 0)
        health_grade = context.get("health_grade", HealthGrade.F)
        
        # Fail fast on global thresholds
        if confidence < self.min_confidence:
            return PolicyDecision(
                policy_id=self.id,
                policy_name=self.name,
                action=PolicyAction.GATE,
                reason=f"Confidence {confidence:.2f} below minimum {self.min_confidence:.2f}",
                matched_rule=None,
                escalation=self.default_escalation,
                requires_audit=self.audit_denied_decisions,
            )
        
        if compare_grades(health_grade, self.min_health_grade) < 0:
            return PolicyDecision(
                policy_id=self.id,
                policy_name=self.name,
                action=PolicyAction.GATE,
                reason=f"Health grade {health_grade.value} below minimum {self.min_health_grade.value}",
                matched_rule=None,
                escalation=self.default_escalation,
                requires_audit=self.audit_denied_decisions,
            )
        
        # Evaluate rules in order
        for rule in self.rules:
            if rule.evaluate(context):
                return PolicyDecision(
                    policy_id=self.id,
                    policy_name=self.name,
                    action=rule.action,
                    reason=rule.description,
                    matched_rule=rule.name,
                    escalation=rule.escalation,
                    requires_audit=rule.requires_audit or self.audit_all_decisions,
                    audit_reason=rule.audit_reason,
                )
        
        # No rules matched - use default
        return PolicyDecision(
            policy_id=self.id,
            policy_name=self.name,
            action=self.default_action,
            reason="No specific rules matched",
            matched_rule=None,
            escalation=self.default_escalation,
            requires_audit=self.audit_all_decisions,
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "PolicyType",
    "PolicyAction",
    "EscalationLevel",
    "HealthGrade",
    "GRADE_ORDER",
    
    # Functions
    "grade_to_rank",
    "compare_grades",
    
    # Models
    "PolicyRule",
    "PolicyDecision",
    "DecisionPolicy",
]
