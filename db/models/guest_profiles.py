"""
Guest Profile Model

Persists a cross-stay memory for returning guests, keyed by phone + email.
Populated at session close (or feedback submission) and surfaced to the
concierge at session creation time so repeat guests are recognised and
served better from the very first message.

What gets remembered:
  - Stay history (properties visited, dates, party size)
  - Preferences (bed type, floor, parking, dietary, activities)
  - Feedback arc (CSAT trend, written comments across trips)
  - Upsell history (what they booked before → likely to book again)
  - Escalation history (what went wrong → proactively prevent recurrence)
  - Concierge persona they interacted with (for continuity)

Design decisions:
  - Keyed by (tenant_id, phone) with email as secondary lookup index.
    Phone is more reliable as a unique identifier for STR guests than email.
  - All preference data lives in JSONB so we can extend without migrations.
  - stay_history is a JSONB array capped at 20 entries (oldest pruned first).
  - This table is NEVER used for cross-operator lookups — tenant_id is
    always scoped so operator A can never see operator B's guest data.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TenantMixin


MAX_STAY_HISTORY = 20   # keep last N stays per guest per operator


class GuestProfileModel(Base, TenantMixin):
    """
    Long-lived guest record that spans multiple reservations.

    Created on first checkout, updated on every subsequent checkout.
    Matched at session-creation time via phone → email → (first+last) fallback.
    """

    __tablename__ = "guest_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # ── Identity (matching keys) ──────────────────────────────────────────────
    phone: Mapped[str | None] = mapped_column(String(50), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))

    # ── Repeat-guest stats ────────────────────────────────────────────────────
    total_stays: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_nights: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_party_size: Mapped[float | None] = mapped_column(Float)

    # ── Feedback arc ──────────────────────────────────────────────────────────
    avg_csat: Mapped[float | None] = mapped_column(Float)           # rolling average
    last_csat: Mapped[int | None] = mapped_column(Integer)          # 1-5
    csat_trend: Mapped[str | None] = mapped_column(String(20))      # up / flat / down
    # "Would recommend" ratio (0.0 – 1.0)
    recommend_rate: Mapped[float | None] = mapped_column(Float)

    # ── Preferences (JSONB — extend freely) ───────────────────────────────────
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Schema (illustrative — not enforced):
    # {
    #   "dietary":       ["gluten-free", "vegetarian"],
    #   "activities":    ["fishing", "kayaking"],     # booked in past stays
    #   "amenities":     ["pool_heat", "bikes"],
    #   "avoid":         ["ground_floor"],
    #   "party_type":    "family",                    # family / couple / group / solo
    #   "travel_reason": "vacation",
    #   "pet_owner":     true,
    #   "upsells":       ["late_checkout", "beach_chairs"],  # booked before
    #   "custom_notes":  "Loves sunrise properties. Always asks about fishing."
    # }

    # ── Stay history (array of compact stay records, newest first) ────────────
    stay_history: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # Each entry:
    # {
    #   "session_token":    "gh_abc123",
    #   "reservation_id":   "RES-001",
    #   "property_code":    "BH-042",
    #   "property_name":    "Sunset Dunes",
    #   "check_in":         "2025-06-14",
    #   "check_out":        "2025-06-21",
    #   "nights":           7,
    #   "num_guests":       4,
    #   "csat":             5,
    #   "would_recommend":  true,
    #   "feedback_text":    "Amazing stay, loved the pool!",
    #   "upsells_booked":   ["beach_chairs", "late_checkout"],
    #   "escalations":      [],
    #   "closed_at":        "2025-06-21T10:30:00Z"
    # }

    # ── Escalation history ────────────────────────────────────────────────────
    escalation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_escalation_reason: Mapped[str | None] = mapped_column(String(100))
    # Full escalation records live in concierge_escalations — this is a summary

    # ── Upsell history ────────────────────────────────────────────────────────
    upsell_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upsells_ever_booked: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # Deduplicated list of activity_type strings booked across all stays

    # ── Timestamps ────────────────────────────────────────────────────────────
    first_stay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Primary lookup: phone within tenant
        Index("ix_guest_profile_tenant_phone",  "tenant_id", "phone"),
        # Secondary lookup: email within tenant
        Index("ix_guest_profile_tenant_email",  "tenant_id", "email"),
        # Dashboard queries: sort by last stay
        Index("ix_guest_profile_tenant_last_stay", "tenant_id", "last_stay_at"),
    )

    # ── Helper: build concierge context snippet ───────────────────────────────
    def to_concierge_context(self) -> dict:
        """
        Returns a compact dict injected into the concierge system prompt
        when a repeat guest is detected.  Kept small — only actionable facts.
        """
        last_stay = self.stay_history[0] if self.stay_history else {}
        upsells = self.upsells_ever_booked or []
        prefs = self.preferences or {}

        return {
            "is_repeat_guest":      True,
            "total_stays":          self.total_stays,
            "last_property":        last_stay.get("property_name"),
            "last_check_in":        last_stay.get("check_in"),
            "avg_csat":             self.avg_csat,
            "csat_trend":           self.csat_trend,
            "past_upsells":         upsells,
            "dietary":              prefs.get("dietary", []),
            "activities":           prefs.get("activities", []),
            "party_type":           prefs.get("party_type"),
            "pet_owner":            prefs.get("pet_owner", False),
            "custom_notes":         prefs.get("custom_notes"),
            "escalation_history":   self.escalation_count > 0,
            "last_escalation":      self.last_escalation_reason,
        }

    def to_prompt_snippet(self) -> str:
        """
        One-paragraph text block for injection into the LLM system prompt.
        Only generated when total_stays > 1 so first-time guests see no change.
        """
        if self.total_stays <= 1:
            return ""

        last_stay = self.stay_history[0] if self.stay_history else {}
        lines = [
            f"RETURNING GUEST — {self.total_stays} stays with us"
            + (f", most recently at {last_stay.get('property_name')} ({last_stay.get('check_in', '')[:7]})" if last_stay else "")
            + "."
        ]

        prefs = self.preferences or {}
        if prefs.get("activities"):
            lines.append(f"Past activities: {', '.join(prefs['activities'][:3])}.")
        if prefs.get("dietary"):
            lines.append(f"Dietary: {', '.join(prefs['dietary'])}.")
        if prefs.get("party_type"):
            lines.append(f"Travel type: {prefs['party_type']}.")
        if self.upsells_ever_booked:
            lines.append(f"Has booked upsells before: {', '.join(self.upsells_ever_booked[:4])}.")
        if self.escalation_count > 0:
            lines.append(
                f"Had {self.escalation_count} escalation(s) in past stays"
                + (f" (most recent: {self.last_escalation_reason})" if self.last_escalation_reason else "")
                + " — be proactive about checking for issues."
            )
        if prefs.get("custom_notes"):
            lines.append(f"Note: {prefs['custom_notes']}")

        return " ".join(lines)
