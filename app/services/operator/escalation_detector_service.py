from __future__ import annotations

from typing import Any

from app.services.operator.safety_protocol_service import get_safety_protocol_service


def _blob(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "reason",
            "summary",
            "last_message",
            "guest_update_note",
            "resolution_notes",
        )
    ).lower()


class EscalationDetectorService:
    def detect(self, row: dict[str, Any], workflow: dict[str, Any], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        text_blob = _blob(row)
        reason = str(row.get("reason") or "").lower()
        priority = str(row.get("priority") or "").lower()
        workflow_stage = str(workflow.get("stage") or "")
        vendor_state = str(workflow.get("vendor_state") or "")
        guest_state = str(workflow.get("guest_update_state") or "")
        signals: dict[str, Any] = {
            "maintenance_issue": False,
            "arrival_or_turnover_issue": False,
            "cleaning_or_turnover_issue": False,
            "vendor_dispatch_needed": False,
            "guest_eta_ready": False,
            "owner_internal_update_needed": False,
            "accounting_claim_handoff_needed": False,
            "safety_or_claims_risk": False,
            "life_safety_emergency": False,
            "booking_hold_required": False,
            "human_ack_required": False,
            "safety_protocol": {},
            "primary_domain": "general_ops",
            "evidence": [],
        }

        maintenance_keywords = (
            "maintenance", "repair", "broken", "ac", "hvac", "plumb", "electric",
            "leak", "mold", "pest", "dirty", "lock", "door", "water damage",
        )
        accounting_keywords = (
            "refund", "charge", "billing", "reimburse", "compensation", "claim",
            "insurance", "damage", "deposit", "chargeback",
        )
        safety_keywords = ("safety", "fire", "flood", "gas", "injured", "unsafe", "911")
        turnover_keywords = (
            "check in", "check-in", "checkin", "arrival", "arrive", "access code",
            "door code", "lockbox", "turnover", "checkout", "check-out", "cleaning",
            "housekeeping", "linen", "ready yet", "not ready",
        )
        cleaning_keywords = ("cleaning", "dirty", "housekeeping", "trash", "laundry", "linens", "not ready")

        if reason in {"maintenance", "property_issue", "complaint"} or any(token in text_blob for token in maintenance_keywords):
            signals["maintenance_issue"] = True
            signals["evidence"].append("maintenance_or_property_issue")

        if any(token in text_blob for token in turnover_keywords):
            signals["arrival_or_turnover_issue"] = True
            signals["evidence"].append("arrival_or_turnover_signal")

        if any(token in text_blob for token in cleaning_keywords):
            signals["cleaning_or_turnover_issue"] = True
            signals["evidence"].append("cleaning_or_turnover_issue")

        if signals["maintenance_issue"] and workflow_stage != "resolved" and vendor_state in {"", "not_started", "selected", "contacted"}:
            signals["vendor_dispatch_needed"] = True
            signals["evidence"].append("vendor_dispatch_needed")

        if signals["cleaning_or_turnover_issue"] and workflow_stage != "resolved" and vendor_state in {"", "not_started", "selected", "contacted"}:
            signals["vendor_dispatch_needed"] = True
            signals["evidence"].append("cleaning_dispatch_needed")

        if vendor_state in {"failed", "reassigned", "cancelled"} and workflow_stage != "resolved":
            signals["vendor_dispatch_needed"] = True
            signals["owner_internal_update_needed"] = True
            signals["evidence"].append("vendor_dispatch_recovery_needed")

        eta_minutes = workflow.get("vendor", {}).get("eta_minutes")
        if eta_minutes is not None and workflow_stage != "resolved" and guest_state not in {"sent_to_guest", "updated"}:
            signals["guest_eta_ready"] = True
            signals["evidence"].append("vendor_eta_ready_for_guest")

        if (
            priority in {"urgent", "high"}
            or workflow.get("sla", {}).get("ack_breached")
            or workflow.get("sla", {}).get("resolve_breached")
            or signals["arrival_or_turnover_issue"]
        ):
            signals["owner_internal_update_needed"] = True
            signals["evidence"].append("high_priority_or_sla")

        safety_protocol = get_safety_protocol_service().evaluate(text_blob, policy=policy)
        signals["safety_protocol"] = safety_protocol
        if any(token in text_blob for token in safety_keywords) or safety_protocol.get("severity") != "none":
            signals["safety_or_claims_risk"] = True
            signals["life_safety_emergency"] = bool(safety_protocol.get("emergency_override"))
            signals["booking_hold_required"] = bool(safety_protocol.get("booking_hold_required"))
            signals["human_ack_required"] = bool(safety_protocol.get("human_ack_required"))
            signals["owner_internal_update_needed"] = True
            signals["accounting_claim_handoff_needed"] = True
            signals["evidence"].append("safety_risk")

        if reason in {"billing", "safety"} or any(token in text_blob for token in accounting_keywords):
            signals["accounting_claim_handoff_needed"] = True
            signals["evidence"].append("billing_or_claim_signal")
        elif vendor_state in {"failed", "reassigned"}:
            signals["accounting_claim_handoff_needed"] = True
            signals["evidence"].append("vendor_failure_accounting_review")

        if signals["safety_or_claims_risk"]:
            signals["primary_domain"] = "safety_claims"
        elif signals["accounting_claim_handoff_needed"]:
            signals["primary_domain"] = "claims_billing"
        elif signals["cleaning_or_turnover_issue"] or signals["arrival_or_turnover_issue"]:
            signals["primary_domain"] = "arrival_turnover"
        elif signals["maintenance_issue"]:
            signals["primary_domain"] = "maintenance"

        return signals


_SERVICE = EscalationDetectorService()


def get_escalation_detector_service() -> EscalationDetectorService:
    return _SERVICE
