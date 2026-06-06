"""
Decision Policies - First-Class Objects.

Enterprise customers love policy control.
Regulators love auditable logic.
This is governance as a feature.

Policies define:
- Confidence thresholds
- Allowed actions
- Gating rules
- Audit requirements

Pairs with signal gating for complete decision governance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.services.signals.signal_contract import SignalType, ConfidenceThresholds
from app.services.health.signal_health import HealthGrade


# =============================================================================
# POLICY TYPES
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


# =============================================================================
# POLICY MODELS
# =============================================================================

@dataclass
class PolicyRule:
    """
    A single rule within a policy.
    
    Rules are evaluated in order; first match wins.
    """
    name: str
    description: str
    
    # Conditions
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    min_health_grade: Optional[HealthGrade] = None
    required_signals: Optional[Set[SignalType]] = None
    
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
        # Check confidence
        if self.min_confidence is not None:
            if context.get("confidence", 0) < self.min_confidence:
                return False
        
        if self.max_confidence is not None:
            if context.get("confidence", 1) > self.max_confidence:
                return False
        
        # Check health grade
        if self.min_health_grade is not None:
            grade = context.get("health_grade")
            if grade:
                grade_order = [HealthGrade.F, HealthGrade.D, HealthGrade.C, HealthGrade.B, HealthGrade.A]
                if grade_order.index(grade) < grade_order.index(self.min_health_grade):
                    return False
        
        # Check required signals
        if self.required_signals:
            present = context.get("present_signals", set())
            if not self.required_signals.issubset(present):
                return False
        
        # Check value thresholds
        value = context.get("value")
        if value is not None:
            if self.max_value is not None and value > self.max_value:
                return False
            if self.min_value is not None and value < self.min_value:
                return False
        
        return True


@dataclass
class DecisionPolicy:
    """
    A complete decision policy.
    
    Policies are versioned, auditable configurations that control
    how the system makes decisions.
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
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    
    def evaluate(self, context: Dict[str, Any]) -> "PolicyDecision":
        """
        Evaluate policy against context.
        
        Returns PolicyDecision with action and audit trail.
        """
        # Check global thresholds first
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
        
        grade_order = [HealthGrade.F, HealthGrade.D, HealthGrade.C, HealthGrade.B, HealthGrade.A]
        if grade_order.index(health_grade) < grade_order.index(self.min_health_grade):
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


@dataclass
class PolicyDecision:
    """
    Result of policy evaluation.
    
    This is the audit trail for every decision.
    """
    policy_id: UUID
    policy_name: str
    
    # Decision
    action: PolicyAction
    reason: str
    
    # Which rule matched
    matched_rule: Optional[str]
    
    # Escalation
    escalation: EscalationLevel = EscalationLevel.NONE
    
    # Audit
    requires_audit: bool = False
    audit_reason: Optional[str] = None
    
    # Timestamp
    decided_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_allowed(self) -> bool:
        """Is the action allowed?"""
        return self.action == PolicyAction.ALLOW
    
    def is_denied(self) -> bool:
        """Is the action denied?"""
        return self.action == PolicyAction.DENY
    
    def needs_escalation(self) -> bool:
        """Does this need escalation?"""
        return self.escalation != EscalationLevel.NONE
    
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
            "decided_at": self.decided_at.isoformat(),
        }


# =============================================================================
# PRESET POLICIES
# =============================================================================

class PresetPolicies:
    """
    Preset policy configurations.
    
    These are starting points that can be customized.
    """
    
    @staticmethod
    def high_confidence_pricing() -> DecisionPolicy:
        """
        High confidence pricing policy.
        
        Conservative - requires strong signals for any pricing action.
        """
        return DecisionPolicy(
            name="High Confidence Pricing",
            description="Conservative pricing policy requiring strong signal confidence",
            policy_type=PolicyType.PRICING,
            min_confidence=0.70,
            min_health_grade=HealthGrade.B,
            max_operator_delta=0.10,
            max_discount=0.15,
            automation_confidence_threshold=0.85,
            rules=[
                PolicyRule(
                    name="high_confidence_allow",
                    description="Allow with high confidence",
                    min_confidence=0.80,
                    min_health_grade=HealthGrade.A,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="moderate_confidence_audit",
                    description="Allow but audit at moderate confidence",
                    min_confidence=0.70,
                    min_health_grade=HealthGrade.B,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                    audit_reason="Moderate confidence decision",
                ),
                PolicyRule(
                    name="low_confidence_escalate",
                    description="Escalate low confidence decisions",
                    max_confidence=0.70,
                    action=PolicyAction.ESCALATE,
                    escalation=EscalationLevel.MANAGER,
                ),
            ],
        )
    
    @staticmethod
    def standard_discount() -> DecisionPolicy:
        """
        Standard discount policy.
        
        Balanced approach to discount requests.
        """
        return DecisionPolicy(
            name="Standard Discount Policy",
            description="Balanced discount approval policy",
            policy_type=PolicyType.DISCOUNT,
            min_confidence=0.60,
            min_health_grade=HealthGrade.C,
            max_discount=0.25,
            rules=[
                PolicyRule(
                    name="small_discount_allow",
                    description="Auto-approve small discounts",
                    max_value=0.10,  # Up to 10%
                    min_confidence=0.50,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="medium_discount_audit",
                    description="Approve medium discounts with audit",
                    max_value=0.20,
                    min_confidence=0.60,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                ),
                PolicyRule(
                    name="large_discount_escalate",
                    description="Escalate large discounts",
                    min_value=0.20,
                    action=PolicyAction.ESCALATE,
                    escalation=EscalationLevel.MANAGER,
                ),
            ],
        )
    
    @staticmethod
    def voice_conservative() -> DecisionPolicy:
        """
        Conservative voice policy.
        
        What the concierge can and cannot say.
        """
        return DecisionPolicy(
            name="Conservative Voice Policy",
            description="Strict limits on voice claims",
            policy_type=PolicyType.VOICE,
            min_confidence=0.65,
            min_health_grade=HealthGrade.C,
            rules=[
                PolicyRule(
                    name="high_confidence_claim",
                    description="Allow specific claims with high confidence",
                    min_confidence=0.75,
                    min_health_grade=HealthGrade.B,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="moderate_soft_claim",
                    description="Allow soft language at moderate confidence",
                    min_confidence=0.60,
                    action=PolicyAction.ALLOW,
                    requires_audit=False,
                ),
                PolicyRule(
                    name="low_confidence_gate",
                    description="Gate claims at low confidence",
                    max_confidence=0.60,
                    action=PolicyAction.GATE,
                ),
            ],
            default_action=PolicyAction.GATE,
        )
    
    @staticmethod
    def institutional_investment() -> DecisionPolicy:
        """
        Institutional investment policy.
        
        For allocators who need defensible analysis.
        """
        return DecisionPolicy(
            name="Institutional Investment Policy",
            description="High standards for investment recommendations",
            policy_type=PolicyType.INVESTMENT,
            min_confidence=0.70,
            min_health_grade=HealthGrade.B,
            audit_all_decisions=True,
            rules=[
                PolicyRule(
                    name="strong_recommendation",
                    description="Strong buy/hold recommendation",
                    min_confidence=0.80,
                    min_health_grade=HealthGrade.A,
                    required_signals={
                        SignalType.SEASONALITY_CURVE,
                        SignalType.PLATFORM_DOMINANCE,
                        SignalType.AMENITY_LIFT,
                    },
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                ),
                PolicyRule(
                    name="qualified_recommendation",
                    description="Recommendation with caveats",
                    min_confidence=0.65,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                    audit_reason="Qualified recommendation - review caveats",
                ),
            ],
            default_action=PolicyAction.GATE,
            default_escalation=EscalationLevel.DIRECTOR,
        )


# =============================================================================
# POLICY SERVICE
# =============================================================================

class PolicyService:
    """
    Policy Service.
    
    Manages policy evaluation and audit logging.
    """
    
    def __init__(self):
        self.version = "1.0.0"
        self._policies: Dict[str, DecisionPolicy] = {}
        self._audit_log: List[Dict[str, Any]] = []
        
        # Load preset policies
        self._load_presets()
    
    def _load_presets(self):
        """Load preset policies."""
        self._policies["high_confidence_pricing"] = PresetPolicies.high_confidence_pricing()
        self._policies["standard_discount"] = PresetPolicies.standard_discount()
        self._policies["voice_conservative"] = PresetPolicies.voice_conservative()
        self._policies["institutional_investment"] = PresetPolicies.institutional_investment()
    
    def get_policy(self, name: str) -> Optional[DecisionPolicy]:
        """Get a policy by name."""
        return self._policies.get(name)
    
    def register_policy(self, policy: DecisionPolicy) -> None:
        """Register a custom policy."""
        self._policies[policy.name] = policy
    
    def evaluate(
        self,
        policy_name: str,
        context: Dict[str, Any],
    ) -> PolicyDecision:
        """
        Evaluate a policy.
        
        Args:
            policy_name: Name of policy to evaluate
            context: Decision context (confidence, health_grade, value, etc.)
        
        Returns:
            PolicyDecision with action and audit info
        """
        policy = self._policies.get(policy_name)
        if not policy:
            raise ValueError(f"Unknown policy: {policy_name}")
        
        decision = policy.evaluate(context)
        
        # Log if required
        if decision.requires_audit:
            self._audit_log.append({
                **decision.to_audit_record(),
                "context": context,
            })
        
        return decision
    
    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit log entries."""
        return self._audit_log[-limit:]


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[PolicyService] = None


def get_policy_service() -> PolicyService:
    """Get policy service singleton."""
    global _service
    if _service is None:
        _service = PolicyService()
    return _service


def evaluate_policy(
    policy_name: str,
    confidence: float,
    health_grade: HealthGrade,
    value: Optional[float] = None,
    **extra_context,
) -> PolicyDecision:
    """
    Evaluate a policy.
    
    Example:
        decision = evaluate_policy(
            "standard_discount",
            confidence=0.72,
            health_grade=HealthGrade.B,
            value=0.15,  # 15% discount requested
        )
        
        if decision.is_allowed():
            approve_discount()
        elif decision.needs_escalation():
            escalate_to(decision.escalation)
    """
    context = {
        "confidence": confidence,
        "health_grade": health_grade,
        "value": value,
        **extra_context,
    }
    return get_policy_service().evaluate(policy_name, context)
