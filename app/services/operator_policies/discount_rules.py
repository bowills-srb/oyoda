"""Structured operator policy helpers for Phase 4.3-A."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class DiscountCondition(BaseModel):
    kind: Literal[
        "gap_night_available",
        "long_stay",
        "last_minute",
        "repeat_guest",
    ]
    min_nights: Optional[int] = Field(default=None, ge=1, le=365)
    booking_window_days: Optional[int] = Field(default=None, ge=0, le=365)

    @model_validator(mode="after")
    def validate_shape(self) -> "DiscountCondition":
        if self.kind == "long_stay" and self.min_nights is None:
            raise ValueError("min_nights is required for long_stay conditions")
        if self.kind == "last_minute" and self.booking_window_days is None:
            raise ValueError("booking_window_days is required for last_minute conditions")
        return self


class DiscountOffer(BaseModel):
    discount_pct: int = Field(ge=0, le=100)
    max_value_usd: Optional[float] = Field(default=None, ge=0)


class DiscountRule(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal[
        "next_night_extension",
        "long_stay_discount",
        "last_minute_discount",
        "repeat_guest_discount",
    ]
    active: bool = True
    condition: DiscountCondition
    offer: DiscountOffer
    notes: Optional[str] = Field(default=None, max_length=500)


class DiscountPolicies(BaseModel):
    rules: List[DiscountRule] = Field(default_factory=list, max_length=20)

    @field_validator("rules")
    @classmethod
    def unique_ids(cls, rules: List[DiscountRule]) -> List[DiscountRule]:
        ids = [rule.id for rule in rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rule ids must be unique")
        return rules


def validate_discount_policies(raw: Any) -> Dict[str, Any]:
    """Validate incoming JSONB payload for operator discount rules."""
    if raw in (None, {}):
        return {"rules": []}
    return DiscountPolicies.model_validate(raw).model_dump()


def default_operator_policies() -> Dict[str, Any]:
    """Stable default shape for unauthored operator policy state."""
    return {
        "_authored": False,
        "check_in_time": "4:00 PM",
        "check_out_time": "10:00 AM",
        "late_checkout_available": True,
        "late_checkout_max_time": "2:00 PM",
        "late_checkout_fee": 50.0,
        "late_checkout_requires_approval": False,
        "early_checkin_available": True,
        "early_checkin_earliest": "1:00 PM",
        "early_checkin_fee": 0.0,
        "early_checkin_subject_to_availability": True,
        "cancellation_full_refund_days": 30,
        "cancellation_partial_refund_days": 14,
        "cancellation_partial_refund_percent": 50,
        # Deprecated for Brain reads in Phase 4.3-A.1. Property-level
        # allow/deny is authoritative; this remains only for backwards
        # compatibility with older policy surfaces until cleanup.
        "pets_allowed": "no",
        "pet_policy": "not_allowed",
        "pet_fee": 0.0,
        "pet_max_weight": None,
        "pet_restricted_breeds": [],
        "pet_notes": None,
        "pool_heat_available": False,
        "pool_heat_daily_fee": 50.0,
        "pool_heat_advance_notice_hours": 48,
        "beach_chairs_included": False,
        "beach_chair_rental_partners": [],
        "discount_policies": {"rules": []},
        "additional_policies": {},
        "support_phone": None,
        "support_email": None,
        "emergency_phone": None,
    }


def normalize_operator_policies(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a DB row onto the stable default policy shape."""
    base = default_operator_policies()
    if not row:
        return base

    normalized = {**base, **row}
    normalized["_authored"] = True
    normalized["discount_policies"] = validate_discount_policies(normalized.get("discount_policies"))
    normalized["additional_policies"] = normalized.get("additional_policies") or {}
    normalized["pet_restricted_breeds"] = normalized.get("pet_restricted_breeds") or []
    normalized["beach_chair_rental_partners"] = normalized.get("beach_chair_rental_partners") or []

    pets_allowed = str(normalized.get("pets_allowed") or "no").strip().lower()
    normalized["pet_policy"] = "allowed" if pets_allowed in {"yes", "some_properties"} else "not_allowed"
    return normalized


__all__ = [
    "DiscountCondition",
    "DiscountOffer",
    "DiscountPolicies",
    "DiscountRule",
    "ValidationError",
    "default_operator_policies",
    "normalize_operator_policies",
    "validate_discount_policies",
]
