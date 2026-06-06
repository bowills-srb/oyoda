from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.services.operator.escalation_detector_service import get_escalation_detector_service


GUEST_PREFIXES = ("guest:", "traveler:", "renter:", "customer:")
HOST_PREFIXES = ("host:", "operator:", "manager:", "concierge:", "agent:")


@dataclass
class ThreadTurn:
    role: str
    text: str


class HistoricalThreadEvaluator:
    def analyze_text(
        self,
        text: str,
        *,
        source_name: Optional[str] = None,
    ) -> dict[str, Any]:
        turns, mode = self._parse_turns_auto(text)
        pairs = self._pair_qa(turns)
        domains = Counter()
        examples: list[dict[str, Any]] = []

        for question, answer in pairs:
            workflow = {
                "stage": "detected",
                "vendor_state": "not_started",
                "guest_update_state": "pending",
                "vendor": {},
                "sla": {"ack_breached": False, "resolve_breached": False},
            }
            row = {
                "reason": self._reason_from_text(question),
                "summary": question,
                "last_message": question,
                "resolution_notes": answer,
                "priority": self._priority_from_text(question),
                "guest_update_note": answer,
            }
            signals = get_escalation_detector_service().detect(row, workflow)
            domains.update([signals.get("primary_domain") or "general_ops"])
            examples.append(
                {
                    "question": question,
                    "answer": answer,
                    "signals": signals,
                }
            )

        return {
            "source_name": source_name or "thread",
            "parse_mode": mode,
            "turn_count": len(turns),
            "guest_turn_count": len([turn for turn in turns if turn.role == "guest"]),
            "host_turn_count": len([turn for turn in turns if turn.role == "host"]),
            "qa_pair_count": len(pairs),
            "domain_counts": dict(domains),
            "cases": examples,
        }

    def build_review_template(
        self,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_name": analysis.get("source_name"),
            "parse_mode": analysis.get("parse_mode"),
            "review_items": [
                {
                    "question": case["question"],
                    "expected_property_binding": "",
                    "expected_route": "",
                    "expected_asks": [],
                    "expected_kb_coverage": "",
                    "expected_draft_quality": "",
                    "detected_domain": (case.get("signals") or {}).get("primary_domain"),
                    "notes": "",
                }
                for case in analysis.get("cases", [])
            ],
        }

    def _parse_turns_auto(self, text: str) -> tuple[list[ThreadTurn], str]:
        labeled = self._parse_turns(text)
        if labeled:
            return labeled, "labeled"
        unlabeled = self._parse_unlabeled_turns(text)
        if unlabeled:
            return unlabeled, "unlabeled_alternating"
        return [], "none"

    def _parse_turns(self, text: str) -> list[ThreadTurn]:
        turns: list[ThreadTurn] = []
        current_role: Optional[str] = None
        buffer: list[str] = []

        def flush() -> None:
            nonlocal current_role, buffer
            if current_role and buffer:
                content = "\n".join(buffer).strip()
                if content:
                    turns.append(ThreadTurn(role=current_role, text=content))
            current_role = None
            buffer = []

        for raw in text.splitlines():
            line = raw.rstrip()
            lower = line.lower().strip()
            if not lower:
                if buffer:
                    buffer.append("")
                continue
            is_guest = any(lower.startswith(prefix) for prefix in GUEST_PREFIXES)
            is_host = any(lower.startswith(prefix) for prefix in HOST_PREFIXES)
            if is_guest or is_host:
                flush()
                current_role = "guest" if is_guest else "host"
                line = re.sub(r"^[A-Za-z ]+:\s*", "", line, count=1)
                buffer.append(self._normalize_line(line))
                continue
            if current_role:
                buffer.append(self._normalize_line(line))

        flush()
        return turns

    def _parse_unlabeled_turns(self, text: str) -> list[ThreadTurn]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n+", text) if block.strip()]
        turns: list[ThreadTurn] = []
        current = "guest"
        for block in blocks:
            clean = self._normalize_line(block.replace("\n", " "))
            if clean:
                turns.append(ThreadTurn(role=current, text=clean))
                current = "host" if current == "guest" else "guest"
        return turns

    def _pair_qa(self, turns: list[ThreadTurn]) -> list[tuple[str, Optional[str]]]:
        pairs: list[tuple[str, Optional[str]]] = []
        i = 0
        while i < len(turns):
            turn = turns[i]
            if turn.role != "guest":
                i += 1
                continue
            question = turn.text.strip()
            answer = None
            if i + 1 < len(turns) and turns[i + 1].role == "host":
                answer = turns[i + 1].text.strip()
                i += 2
            else:
                i += 1
            if question:
                pairs.append((question, answer))
        return pairs

    def _priority_from_text(self, text: str) -> str:
        blob = text.lower()
        if any(token in blob for token in ("urgent", "asap", "emergency", "unsafe", "flood", "fire")):
            return "urgent"
        if any(token in blob for token in ("broken", "leak", "refund", "dirty", "not working", "late")):
            return "high"
        return "medium"

    def _reason_from_text(self, text: str) -> str:
        blob = text.lower()
        if any(token in blob for token in ("refund", "billing", "charge", "deposit", "reimburse", "claim")):
            return "billing"
        if any(token in blob for token in ("fire", "flood", "gas", "unsafe", "injured", "911")):
            return "safety"
        if any(token in blob for token in ("check in", "check-in", "checkout", "cleaning", "dirty", "turnover")):
            return "property_issue"
        if any(token in blob for token in ("broken", "repair", "ac", "hvac", "leak", "lock")):
            return "maintenance"
        return "other"

    def _normalize_line(self, line: str) -> str:
        return re.sub(r"\s+", " ", line.strip())


_SERVICE = HistoricalThreadEvaluator()


def get_historical_thread_evaluator() -> HistoricalThreadEvaluator:
    return _SERVICE
