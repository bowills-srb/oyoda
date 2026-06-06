from __future__ import annotations

from typing import Any


class StayReceptivenessService:
    def evaluate(self, row: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        phase = str(row.get("phase") or workflow.get("phase") or "").lower()
        recent_outbound = int(row.get("recent_outbound_count") or 0)
        recent_inbound = int(row.get("recent_inbound_count") or 0)
        pending_outbound = int(row.get("consecutive_outbound_without_reply") or 0)
        notification_count = int(row.get("notification_count") or 0)
        open_escalations = int(row.get("open_escalations") or 0)
        latest_direction = str(row.get("latest_message_direction") or "").lower()

        score = 0.5
        evidence: list[str] = []
        pending_backoff_threshold = 2
        outbound_no_reply_threshold = 3
        notification_threshold = 6

        if phase in {"pre_arrival", "arrival_day"}:
            pending_backoff_threshold = 4
            outbound_no_reply_threshold = 5
            notification_threshold = 9
            score += 0.06
            evidence.append("prearrival_concierge_allowance")
        elif phase in {"post_stay"}:
            pending_backoff_threshold = 3
            outbound_no_reply_threshold = 4
            notification_threshold = 7
        else:
            evidence.append("active_stay_fatigue_guard")

        if recent_inbound > 0:
            score += 0.12
            evidence.append("recent_guest_engagement")
        if recent_inbound >= recent_outbound and recent_inbound > 0:
            score += 0.08
            evidence.append("guest_reply_balance_positive")
        if pending_outbound >= pending_backoff_threshold:
            score -= 0.22
            evidence.append("multiple_outbound_without_reply")
        elif pending_outbound == 1:
            score -= 0.08
            evidence.append("single_outbound_waiting_reply")
        if recent_outbound >= outbound_no_reply_threshold and recent_inbound == 0:
            score -= 0.18
            evidence.append("high_outbound_no_recent_reply")
        if notification_count >= notification_threshold:
            score -= 0.12
            evidence.append("high_notification_volume")
        if open_escalations > 0:
            score -= 0.05
            evidence.append("active_service_issue")
        if latest_direction == "inbound":
            score += 0.08
            evidence.append("guest_initiated_latest_turn")

        score = round(max(0.0, min(1.0, score)), 2)
        if score >= 0.7:
            fatigue_state = "low"
        elif score >= 0.45:
            fatigue_state = "medium"
        else:
            fatigue_state = "high"

        return {
            "score": score,
            "phase": phase or "unknown",
            "fatigue_state": fatigue_state,
            "guest_engaged_recently": recent_inbound > 0,
            "pending_outbound_without_reply": pending_outbound,
            "recent_outbound_count": recent_outbound,
            "recent_inbound_count": recent_inbound,
            "should_backoff_proactive": fatigue_state == "high" or pending_outbound >= pending_backoff_threshold,
            "backoff_thresholds": {
                "pending_outbound": pending_backoff_threshold,
                "outbound_no_reply": outbound_no_reply_threshold,
                "notification_volume": notification_threshold,
            },
            "evidence": evidence,
        }


_SERVICE = StayReceptivenessService()


def get_stay_receptiveness_service() -> StayReceptivenessService:
    return _SERVICE
