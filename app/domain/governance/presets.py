"""
Domain: Governance - Preset Policies.

Standard policy configurations for common use cases.
Pure domain objects - no IO.
"""

from .policies import (
    DecisionPolicy,
    PolicyRule,
    PolicyType,
    PolicyAction,
    EscalationLevel,
    HealthGrade,
)


class PresetPolicies:
    """
    Factory for standard policy configurations.
    
    These are battle-tested defaults for common scenarios.
    """
    
    @staticmethod
    def high_confidence_pricing() -> DecisionPolicy:
        """
        High confidence pricing policy.
        
        For operators who want conservative, defensible pricing.
        """
        return DecisionPolicy(
            name="High Confidence Pricing Policy",
            description="Conservative pricing requiring high confidence",
            policy_type=PolicyType.PRICING,
            min_confidence=0.70,
            min_health_grade=HealthGrade.B,
            rules=[
                PolicyRule(
                    name="high_confidence_allow",
                    description="Allow pricing decisions with high confidence",
                    min_confidence=0.80,
                    min_health_grade=HealthGrade.B,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="moderate_confidence_audit",
                    description="Audit moderate confidence decisions",
                    min_confidence=0.70,
                    max_confidence=0.80,
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
    def aggressive_discount() -> DecisionPolicy:
        """
        Aggressive discount policy.
        
        For operators who want to fill inventory quickly.
        """
        return DecisionPolicy(
            name="Aggressive Discount Policy",
            description="Higher discount thresholds for inventory fill",
            policy_type=PolicyType.DISCOUNT,
            min_confidence=0.50,
            min_health_grade=HealthGrade.C,
            max_discount=0.35,
            rules=[
                PolicyRule(
                    name="moderate_discount_allow",
                    description="Auto-approve moderate discounts",
                    max_value=0.20,
                    min_confidence=0.45,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="large_discount_allow_audit",
                    description="Allow large discounts with audit",
                    max_value=0.30,
                    min_confidence=0.55,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                ),
                PolicyRule(
                    name="very_large_discount_escalate",
                    description="Escalate very large discounts",
                    min_value=0.30,
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
        High bar for making claims to guests.
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
    def voice_permissive() -> DecisionPolicy:
        """
        Permissive voice policy.
        
        For operators comfortable with more claims.
        """
        return DecisionPolicy(
            name="Permissive Voice Policy",
            description="More lenient voice claims policy",
            policy_type=PolicyType.VOICE,
            min_confidence=0.50,
            min_health_grade=HealthGrade.C,
            rules=[
                PolicyRule(
                    name="moderate_confidence_claim",
                    description="Allow claims at moderate confidence",
                    min_confidence=0.55,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="low_confidence_soft_claim",
                    description="Allow hedged claims at lower confidence",
                    min_confidence=0.45,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                ),
            ],
            default_action=PolicyAction.GATE,
        )
    
    @staticmethod
    def institutional_investment() -> DecisionPolicy:
        """
        Institutional investment policy.
        
        For allocators who need defensible analysis.
        Very high standards.
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
                    required_signal_types={
                        "seasonality_curve",
                        "platform_dominance",
                        "amenity_lift",
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
    
    @staticmethod
    def expansion_analysis() -> DecisionPolicy:
        """
        Expansion analysis policy.
        
        For market expansion recommendations.
        """
        return DecisionPolicy(
            name="Expansion Analysis Policy",
            description="Standards for expansion recommendations",
            policy_type=PolicyType.EXPANSION,
            min_confidence=0.55,
            min_health_grade=HealthGrade.C,
            rules=[
                PolicyRule(
                    name="high_confidence_expansion",
                    description="Strong expansion recommendation",
                    min_confidence=0.70,
                    min_health_grade=HealthGrade.B,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="moderate_expansion_audit",
                    description="Moderate confidence expansion",
                    min_confidence=0.55,
                    action=PolicyAction.ALLOW,
                    requires_audit=True,
                ),
            ],
            default_action=PolicyAction.GATE,
        )
    
    @staticmethod
    def full_automation() -> DecisionPolicy:
        """
        Full automation policy.
        
        For operators who want maximum automation.
        """
        return DecisionPolicy(
            name="Full Automation Policy",
            description="Maximum automation with guardrails",
            policy_type=PolicyType.AUTOMATION,
            min_confidence=0.60,
            min_health_grade=HealthGrade.C,
            allow_automation=True,
            automation_confidence_threshold=0.65,
            rules=[
                PolicyRule(
                    name="auto_approve",
                    description="Auto-approve at threshold",
                    min_confidence=0.65,
                    action=PolicyAction.ALLOW,
                ),
                PolicyRule(
                    name="human_review",
                    description="Require human review below threshold",
                    max_confidence=0.65,
                    action=PolicyAction.ESCALATE,
                    escalation=EscalationLevel.MANAGER,
                ),
            ],
        )


# =============================================================================
# PRESET REGISTRY
# =============================================================================

PRESET_REGISTRY = {
    "high_confidence_pricing": PresetPolicies.high_confidence_pricing,
    "standard_discount": PresetPolicies.standard_discount,
    "aggressive_discount": PresetPolicies.aggressive_discount,
    "voice_conservative": PresetPolicies.voice_conservative,
    "voice_permissive": PresetPolicies.voice_permissive,
    "institutional_investment": PresetPolicies.institutional_investment,
    "expansion_analysis": PresetPolicies.expansion_analysis,
    "full_automation": PresetPolicies.full_automation,
}


def get_preset_policy(name: str) -> DecisionPolicy:
    """Get a preset policy by name."""
    factory = PRESET_REGISTRY.get(name)
    if not factory:
        raise ValueError(f"Unknown preset policy: {name}. Available: {list(PRESET_REGISTRY.keys())}")
    return factory()


def list_preset_names() -> list[str]:
    """List all available preset policy names."""
    return list(PRESET_REGISTRY.keys())


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "PresetPolicies",
    "PRESET_REGISTRY",
    "get_preset_policy",
    "list_preset_names",
]
