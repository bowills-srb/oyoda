from __future__ import annotations

import re
from typing import Any


def _blob(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "guest_name",
            "property_name",
            "latest_message_content",
            "latest_message_intent",
            "last_guest_message",
            "last_operator_message",
        )
    ).lower()


class StayDetectorService:
    def detect(self, row: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        text_blob = _blob(row)
        phase = str(row.get("phase") or workflow.get("phase") or "").lower()
        latest_intent = str(row.get("latest_message_intent") or "").lower()
        open_escalations = int(row.get("open_escalations") or 0)
        guest_update_state = str(workflow.get("guest_update_state") or "").lower()
        vendor = workflow.get("vendor") if isinstance(workflow.get("vendor"), dict) else {}
        vendor_state = str(vendor.get("dispatch_state") or "").lower()
        operations = workflow.get("operations") if isinstance(workflow.get("operations"), dict) else {}
        modules = operations.get("modules") if isinstance(operations.get("modules"), dict) else {}
        tasks = operations.get("tasks") if isinstance(operations.get("tasks"), list) else []
        signals: dict[str, Any] = {
            "urgent_tone": False,
            "knowledge_response_candidate": False,
            "reactive_status_response_needed": False,
            "reactive_response_type": None,
            "proactive_outreach_recommended": False,
            "proactive_backoff_active": False,
            "proactive_touch_type": None,
            "ops_review_needed": False,
            "arrival_issue": False,
            "checkout_issue": False,
            "maintenance_issue": False,
            "turnover_coordination_needed": False,
            "vendor_dispatch_needed": False,
            "guest_eta_ready": False,
            "owner_internal_update_needed": False,
            "accounting_claim_handoff_needed": False,
            "workflow_domain": "guest_stay",
            "evidence": [],
        }

        if any(token in text_blob for token in ("urgent", "asap", "immediately", "right now", "can't get in", "unsafe", "emergency")):
            signals["urgent_tone"] = True
            signals["evidence"].append("urgent_tone")

        arrival_keywords = (
            "check in", "check-in", "checkin", "arrival", "arrive", "door code",
            "lockbox", "access code", "wifi", "parking", "where do we", "get in",
            "code does not work", "can't get in",
        )
        checkout_keywords = (
            "check out", "check-out", "checkout", "late checkout", "early checkin",
            "extend stay", "stay longer", "leave bags", "departure",
        )
        maintenance_keywords = (
            "broken", "not working", "repair", "maintenance", "leak", "ac", "hvac",
            "plumb", "electric", "dirty", "mold", "pest", "lock", "door", "water damage",
        )
        turnover_keywords = (
            "cleaning", "housekeeping", "trash", "linens", "laundry", "turnover",
            "not ready", "still being cleaned", "eta", "ready yet", "check out clean",
        )
        accounting_keywords = (
            "refund", "charge", "billing", "reimburse", "credit", "claim", "insurance",
            "damage", "deposit", "chargeback",
        )

        if phase in {"pre_arrival", "arrival_day"} and any(token in text_blob for token in arrival_keywords):
            signals["arrival_issue"] = True
            signals["evidence"].append("arrival_issue")

        if phase in {"departure_day", "post_stay"} and any(token in text_blob for token in checkout_keywords):
            signals["checkout_issue"] = True
            signals["evidence"].append("checkout_issue")

        if any(token in text_blob for token in maintenance_keywords):
            signals["maintenance_issue"] = True
            signals["evidence"].append("maintenance_issue")

        if any(token in text_blob for token in turnover_keywords):
            signals["turnover_coordination_needed"] = True
            signals["evidence"].append("turnover_coordination_needed")

        if signals["maintenance_issue"] or signals["turnover_coordination_needed"]:
            signals["vendor_dispatch_needed"] = True
            signals["evidence"].append("vendor_dispatch_needed")

        if vendor_state in {"failed", "reassigned", "cancelled"}:
            signals["vendor_dispatch_needed"] = True
            signals["owner_internal_update_needed"] = True
            signals["evidence"].append("vendor_dispatch_recovery_needed")

        if modules.get("turnover_workflows") and any(
            str(task.get("key") or "") == "housekeeping_turnover" and str(task.get("status") or "") in {"pending", "in_progress", "failed", "reassigned", "cancelled"}
            for task in tasks
        ):
            signals["turnover_coordination_needed"] = True
            signals["vendor_dispatch_needed"] = True
            signals["evidence"].append("turnover_rhythm_due")

        eta_minutes = workflow.get("vendor_eta_minutes")
        if eta_minutes is not None and guest_update_state not in {"sent_to_guest", "updated"}:
            signals["guest_eta_ready"] = True
            signals["evidence"].append("guest_eta_ready")

        if (
            latest_intent in {"maintenance_issue", "guest_issue", "request_late_checkout", "request_early_checkin"}
            or open_escalations > 0
            or signals["urgent_tone"]
        ):
            signals["ops_review_needed"] = True
            signals["evidence"].append("ops_review_needed")

        if any(token in text_blob for token in accounting_keywords):
            signals["accounting_claim_handoff_needed"] = True
            signals["evidence"].append("accounting_claim_handoff_needed")
        elif vendor_state in {"failed", "reassigned"}:
            signals["accounting_claim_handoff_needed"] = True
            signals["evidence"].append("vendor_failure_accounting_review")

        question_like = bool(re.search(r"\?|how|where|when|what|can you|could you|do you", text_blob))
        status_followup_like = bool(
            re.search(
                r"\b(update|status|eta|when will|any word|where are they|how much longer|still working|what's happening)\b",
                text_blob,
            )
        )
        if (
            question_like
            and not signals["maintenance_issue"]
            and not signals["turnover_coordination_needed"]
            and open_escalations == 0
        ):
            signals["knowledge_response_candidate"] = True
            signals["evidence"].append("knowledge_response_candidate")

        latest_direction = str(row.get("latest_message_direction") or "").lower()
        if latest_direction == "inbound" and open_escalations > 0:
            signals["reactive_status_response_needed"] = True
            signals["reactive_response_type"] = (
                "status_followup" if status_followup_like else "service_acknowledgement"
            )
            signals["evidence"].append("reactive_status_response_needed")
            if status_followup_like:
                signals["evidence"].append("status_followup")

        if (
            open_escalations > 0
            or signals["urgent_tone"]
            or signals["arrival_issue"]
            or signals["checkout_issue"]
            or signals["vendor_dispatch_needed"]
        ):
            signals["owner_internal_update_needed"] = True
            signals["evidence"].append("owner_internal_update_needed")

        proactive = workflow.get("proactive") if isinstance(workflow.get("proactive"), dict) else {}
        if proactive.get("backoff_active"):
            signals["proactive_backoff_active"] = True
            signals["evidence"].append("proactive_backoff_active")
        if proactive.get("allowed_touch_family") == "service_updates_only":
            signals["evidence"].append("service_updates_only")
        if proactive.get("eligible") and proactive.get("touch_type"):
            signals["proactive_outreach_recommended"] = True
            signals["proactive_touch_type"] = proactive.get("touch_type")
            signals["evidence"].append("proactive_outreach_recommended")

        if signals["accounting_claim_handoff_needed"]:
            signals["workflow_domain"] = "claims_billing"
        elif signals["turnover_coordination_needed"] or signals["checkout_issue"]:
            signals["workflow_domain"] = "turnover"
        elif signals["maintenance_issue"]:
            signals["workflow_domain"] = "maintenance"
        elif signals["arrival_issue"]:
            signals["workflow_domain"] = "arrival"

        return signals


_SERVICE = StayDetectorService()


def get_stay_detector_service() -> StayDetectorService:
    return _SERVICE
