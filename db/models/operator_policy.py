"""
Operator Policy Model

Stores operator-specific policies that the concierge needs to know:
- Check-in/out rules
- Discount policies
- Pet policies
- Pool heat, beach chairs, etc.

These are captured during onboarding and used by the Voice Pod
to give accurate answers to guest questions.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

from app.models.base import Base


class OperatorPolicy(Base):
    """
    Operator-specific policies for concierge responses.
    
    Stored as a mix of structured fields (for common policies)
    and JSONB (for flexible extension).
    """
    __tablename__ = "operator_policies"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(String(100), nullable=True, index=True)
    
    # Check-in/out
    check_in_time = Column(String(20), default="4:00 PM")
    check_out_time = Column(String(20), default="10:00 AM")
    
    # Late checkout policy
    late_checkout_available = Column(Boolean, default=True)
    late_checkout_max_time = Column(String(20), default="2:00 PM")
    late_checkout_fee = Column(Float, default=50.0)
    late_checkout_requires_approval = Column(Boolean, default=False)
    
    # Early check-in policy
    early_checkin_available = Column(Boolean, default=True)
    early_checkin_earliest = Column(String(20), default="1:00 PM")
    early_checkin_fee = Column(Float, default=0.0)
    early_checkin_subject_to_availability = Column(Boolean, default=True)
    
    # Cancellation policy
    cancellation_full_refund_days = Column(Integer, default=30)
    cancellation_partial_refund_days = Column(Integer, default=14)
    cancellation_partial_refund_percent = Column(Integer, default=50)
    
    # Pet policy
    # Deprecated for Brain reads in Phase 4.3-A.1. Property-level
    # allow/deny now comes from canonical property facts (for example
    # amenities.pet_friendly / PMS pet_friendly), while this table
    # remains the home for portfolio-wide fee/restriction defaults.
    pets_allowed = Column(String(50), default="no")  # no, yes, some_properties
    pet_fee = Column(Float, default=0.0)
    pet_max_weight = Column(Integer, nullable=True)
    pet_restricted_breeds = Column(JSONB, default=list)
    pet_notes = Column(Text, nullable=True)
    
    # Pool heat
    pool_heat_available = Column(Boolean, default=False)
    pool_heat_daily_fee = Column(Float, default=50.0)
    pool_heat_advance_notice_hours = Column(Integer, default=48)
    
    # Beach chairs/gear
    beach_chairs_included = Column(Boolean, default=False)
    beach_chair_rental_partners = Column(JSONB, default=list)  # [{name, phone}]
    
    # Upsell revenue rates (USD) — used by /analytics/revenue endpoint.
    # Operators set these during onboarding (or later in the dashboard).
    # If null the endpoint falls back to platform-wide defaults.
    upsell_rates = Column(JSONB, default=None, nullable=True)
    # Schema:
    # {
    #   "late_checkout":   35.0,
    #   "early_checkin":   35.0,
    #   "beach_chairs":    35.0,
    #   "pontoon":        250.0,
    #   "fishing":        180.0,
    #   "dolphin":        120.0,
    #   "golf":           150.0,
    #   "bikes":           40.0,
    #   "spa":            120.0,
    #   "groceries":       15.0,
    #   "mid_stay_clean":  75.0,
    #   "pool_heat":       50.0,
    # }
    # A partial dict is fine — missing keys fall back to platform defaults.

    # Onboarding completion flag for upsell rates
    # null = not asked yet, false = skipped, true = filled in
    upsell_rates_configured = Column(Boolean, default=None, nullable=True)

    # Discounts - stored as JSONB for flexibility
    discount_policies = Column(JSONB, default=dict)
    # Example:
    # {
    #     "last_minute": {"enabled": True, "days": 7, "percent": 15},
    #     "long_stay": {"enabled": True, "nights": 7, "percent": 10},
    #     "repeat_guest": {"enabled": True, "percent": 5},
    #     "military": {"enabled": True, "percent": 10},
    # }
    
    # Additional policies (flexible JSONB)
    additional_policies = Column(JSONB, default=dict)
    # Example:
    # {
    #     "smoking": "No smoking anywhere on property",
    #     "events": "No events or parties without approval",
    #     "quiet_hours": "10pm - 8am",
    #     "max_vehicles": 2,
    # }
    
    # Support contact
    support_phone = Column(String(50), nullable=True)
    support_email = Column(String(255), nullable=True)
    emergency_phone = Column(String(50), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for use in prompts."""
        return {
            "check_in_time": self.check_in_time,
            "check_out_time": self.check_out_time,
            "late_checkout": {
                "available": self.late_checkout_available,
                "max_time": self.late_checkout_max_time,
                "fee": self.late_checkout_fee,
                "requires_approval": self.late_checkout_requires_approval,
            },
            "early_checkin": {
                "available": self.early_checkin_available,
                "earliest": self.early_checkin_earliest,
                "fee": self.early_checkin_fee,
                "subject_to_availability": self.early_checkin_subject_to_availability,
            },
            "cancellation": {
                "full_refund_days": self.cancellation_full_refund_days,
                "partial_refund_days": self.cancellation_partial_refund_days,
                "partial_refund_percent": self.cancellation_partial_refund_percent,
            },
            "pets": {
                "allowed": self.pets_allowed,
                "fee": self.pet_fee,
                "max_weight": self.pet_max_weight,
                "restricted_breeds": self.pet_restricted_breeds or [],
                "notes": self.pet_notes,
            },
            "pool_heat": {
                "available": self.pool_heat_available,
                "daily_fee": self.pool_heat_daily_fee,
                "advance_notice_hours": self.pool_heat_advance_notice_hours,
            },
            "beach_chairs": {
                "included": self.beach_chairs_included,
                "rental_partners": self.beach_chair_rental_partners or [],
            },
            "discounts": self.discount_policies or {},
            "additional": self.additional_policies or {},
            "support": {
                "phone": self.support_phone,
                "email": self.support_email,
                "emergency": self.emergency_phone,
            },
        }
    
    def to_prompt_context(self) -> str:
        """Generate policy context for LLM prompts."""
        lines = []
        
        # Check-in/out
        lines.append(f"Check-in: {self.check_in_time}")
        lines.append(f"Check-out: {self.check_out_time}")
        
        # Late checkout
        if self.late_checkout_available:
            approval = " (requires approval)" if self.late_checkout_requires_approval else ""
            lines.append(f"Late checkout: Available until {self.late_checkout_max_time}, ${self.late_checkout_fee} fee{approval}")
        else:
            lines.append("Late checkout: Not available")
        
        # Early check-in
        if self.early_checkin_available:
            fee = f", ${self.early_checkin_fee} fee" if self.early_checkin_fee > 0 else ""
            lines.append(f"Early check-in: Possible from {self.early_checkin_earliest} (subject to availability){fee}")
        
        # Pets
        if self.pets_allowed == "yes":
            lines.append(f"Pets: Allowed, ${self.pet_fee} fee")
        elif self.pets_allowed == "some_properties":
            lines.append(f"Pets: Allowed at some properties, ${self.pet_fee} fee. Check specific property.")
        else:
            lines.append("Pets: Not allowed")
        
        # Pool heat
        if self.pool_heat_available:
            lines.append(f"Pool heat: ${self.pool_heat_daily_fee}/day, {self.pool_heat_advance_notice_hours}hr notice required")
        
        # Beach chairs
        if self.beach_chairs_included:
            lines.append("Beach chairs: Included")
        elif self.beach_chair_rental_partners:
            partners = ", ".join([f"{p['name']} ({p['phone']})" for p in self.beach_chair_rental_partners])
            lines.append(f"Beach chairs: Rental from {partners}")
        
        # Discounts
        discounts = self.discount_policies or {}
        if discounts.get("last_minute", {}).get("enabled"):
            lm = discounts["last_minute"]
            lines.append(f"Last-minute discount: {lm.get('percent', 15)}% off within {lm.get('days', 7)} days")
        if discounts.get("long_stay", {}).get("enabled"):
            ls = discounts["long_stay"]
            lines.append(f"Long-stay discount: {ls.get('percent', 10)}% off for {ls.get('nights', 7)}+ nights")
        
        return "\n".join(lines)


class OperatorIntegration(Base):
    """
    PMS and data integration configuration for an operator.
    """
    __tablename__ = "operator_integrations"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operator_id = Column(String(100), nullable=False, index=True)
    
    # Integration type
    integration_type = Column(String(50), nullable=False)  # pms, scraper, manual
    
    # PMS-specific
    pms_provider = Column(String(50), nullable=True)  # escapia, guesty, hostaway, track
    pms_api_base_url = Column(String(500), nullable=True)
    pms_credentials_vault_key = Column(String(255), nullable=True)  # Reference to secure vault
    
    # Scraper-specific
    scraper_target_url = Column(String(500), nullable=True)
    scraper_config = Column(JSONB, default=dict)
    
    # Sync settings
    sync_enabled = Column(Boolean, default=True)
    sync_frequency_minutes = Column(Integer, default=60)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_status = Column(String(50), nullable=True)  # success, failed, partial
    last_sync_error = Column(Text, nullable=True)
    last_sync_stats = Column(JSONB, default=dict)  # {properties_synced, bookings_synced, etc}
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OperatorOnboarding(Base):
    """
    Tracks onboarding progress for an operator.
    """
    __tablename__ = "operator_onboarding"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operator_id = Column(String(100), nullable=False, unique=True, index=True)
    
    # Status
    status = Column(String(50), default="pending")  # pending, in_progress, completed, paused
    
    # Steps tracking
    completed_steps = Column(JSONB, default=list)
    # ["basics", "branding", "integration", "policies", "properties", "knowledge_base"]
    
    current_step = Column(String(50), nullable=True)
    
    # Conversation state (for resuming)
    conversation_state = Column(JSONB, default=dict)
    
    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Onboarding agent session
    agent_session_id = Column(String(100), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
