from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any, Dict, List, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.services.messaging_brain.intake.intent_escalator import (
    DEFAULT_ESCALATION_THRESHOLD,
    load_prebooking_escalation_threshold,
)
from app.services.orchestration.messaging_brain_contracts import (
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)

logger = logging.getLogger(__name__)


_CHECK_IN_TIMING_PATTERNS = (
    "early check in",
    "early check-in",
    "late check in",
    "late check-in",
    "how early could we check",
    "how early can we check",
    "arrive early",
    "arrival time",
)

_ACCESS_PATTERNS = (
    "check in time",
    "check-in time",
    "lockbox",
    "door code",
)

_PET_PATTERNS = (
    "pet",
    "dog",
    "cat",
    "puppy",
    "kitten",
    "fur baby",
    "travel with",
)

_REVIEW_PATTERNS = (
    "review",
    "feedback",
    "experience",
    "stay was",
    "trip was",
    "left a review",
    "guest review",
    "thank you for staying",
)


class DeterministicIntakePreFilter:
    """Deterministic-first intake layer for the messaging brain.

    Migrates the proven deterministic pre-booking keyword logic into the brain
    and exposes both the native brain MessageClassification contract and the
    legacy intent details needed for parity checks and gradual cutover.
    """

    name = "DeterministicIntakePreFilter"

    PATTERNS: Dict[str, List[str]] = {
        "availability": ["available", "availability", "open", "book", "reserve", "dates",
                         "january", "february", "march", "april", "may", "june",
                         "july", "august", "september", "october", "november", "december",
                         "weekend", "week", "nights", "check in", "check out"],
        "check_in_process": ["early check in", "early check-in", "late check in", "late check-in",
                             "how early could we check", "how early can we check", "arrive early",
                             "arrival time", "check in time", "check-in time", "lockbox", "door code"],
        "pet_policy": ["pet", "dog", "cat", "puppy", "kitten", "animal", "fur baby",
                        "bring my dog", "travel with"],
        "pricing": ["price", "cost", "rate", "discount", "deal", "negotiate",
                     "weekly rate", "monthly rate", "long stay", "lower"],
        "amenities": ["pool", "hot tub", "jacuzzi", "wifi", "internet", "parking",
                       "garage", "kitchen", "washer", "dryer", "grill", "beach access",
                       "high chair", "pack and play", "pack-and-play", "baby gate",
                       "crib", "beach toys", "beach chairs", "beach chair"],
        "local_area": ["far from", "distance", "beach", "downtown", "restaurant",
                        "airport", "walk", "drive", "minutes", "miles"],
        "group_size": ["sleep", "sleeps", "people", "guests", "person", "group",
                        "family of", "party of", "fit", "accommodate"],
        "accessibility": ["wheelchair", "accessible", "disability", "stair", "elevator",
                           "ada", "ground floor", "mobility"],
        "review_response": ["review", "feedback", "experience", "stay was", "trip was",
                             "left a review", "guest review", "thank you for staying"],
    }

    async def classify(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,
    ) -> MessageClassification:
        classification, _metadata = await self.classify_with_metadata(
            message,
            db_session=db_session,
        )
        return classification

    async def classify_with_metadata(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,
    ) -> tuple[MessageClassification, ClassifierMetadata]:
        tenant_uuid = _coerce_tenant_uuid(message.tenant_id)
        threshold = DEFAULT_ESCALATION_THRESHOLD
        if tenant_uuid is not None:
            threshold = await load_prebooking_escalation_threshold(
                tenant_id=tenant_uuid,
                db=db_session,
            )

        details = await self.classify_with_details(
            message.text or "",
            tenant_id=tenant_uuid,
            db_session=db_session,
        )
        classification = self._to_message_classification(details, message.text or "")
        metadata = ClassifierMetadata(
            classifier_source="deterministic",
            provider_used=None,
            fallback_stage=None,
            latency_ms=0,
            threshold=threshold,
            original_intent=str(details["intent"]),
            original_confidence=float(details["confidence"]),
            escalated=False,
            contradictory_signals=bool(details["contradictory_signals"]),
            legacy_intent=str(details["intent"]),
            matched_terms=list(details.get("matched_terms") or []),
            matched_override_keywords=list(details.get("matched_override_keywords") or []),
            resolved_via_override=bool(details.get("matched_override_keywords")),
            coercion_notes=[
                f"competing_intents:{','.join(details['competing_intents'])}"
            ] if details["competing_intents"] else [],
        )
        return classification, metadata

    async def classify_with_details(
        self,
        message: str,
        *,
        tenant_id: UUID | None = None,
        db_session: Any = None,
    ) -> dict[str, Any]:
        msg = (message or "").lower()
        overrides = await self._load_keyword_overrides(
            tenant_id=tenant_id,
            db_session=db_session,
        )
        patterns = self._merge_patterns(overrides)
        scores: Dict[str, int] = {}
        matched_terms: Dict[str, List[str]] = {}
        matched_override_terms: Dict[str, List[str]] = {}
        for intent, entries in patterns.items():
            intent_matches = [pattern for pattern in entries if pattern in msg]
            hits = len(intent_matches)
            if hits:
                scores[intent] = hits
                matched_terms[intent] = sorted(set(intent_matches))
                override_hits = [
                    pattern
                    for pattern in overrides.get(intent, [])
                    if pattern in msg
                ]
                matched_override_terms[intent] = sorted(set(override_hits))

        if not scores:
            return {
                "intent": "general",
                "confidence": 0.55,
                "scores": {},
                "competing_intents": [],
                "contradictory_signals": False,
                "matched_terms": [],
                "matched_override_keywords": [],
            }

        best = max(scores, key=scores.get)
        total = sum(scores.values())
        best_hits = scores[best]
        competing = sorted(
            (
                (intent, score)
                for intent, score in scores.items()
                if intent != best
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        contradictory_signals = bool(
            competing and best_hits - competing[0][1] <= 1 and len(scores) > 1
        )
        token_count = len(re.findall(r"\w+", msg))
        confidence = 0.35 + min(0.30, best_hits * 0.12) + min(0.30, best_hits / max(total, 1) * 0.30)
        if best_hits == 1:
            confidence -= 0.12
        if token_count >= 25 and best_hits == 1:
            confidence -= 0.12
        if contradictory_signals:
            confidence -= 0.10
        confidence = min(max(confidence, 0.10), 0.95)
        return {
            "intent": best,
            "confidence": round(confidence, 2),
            "scores": scores,
            "competing_intents": [intent for intent, _score in competing[:2]],
            "contradictory_signals": contradictory_signals,
            "matched_terms": matched_terms.get(best, []),
            "matched_override_keywords": matched_override_terms.get(best, []),
        }

    def _merge_patterns(
        self,
        overrides: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        merged = deepcopy(self.PATTERNS)
        for intent, extra_keywords in overrides.items():
            if intent not in merged:
                continue
            existing = {entry.lower() for entry in merged[intent]}
            for keyword in extra_keywords:
                normalized = str(keyword or "").strip().lower()
                if normalized and normalized not in existing:
                    merged[intent].append(normalized)
                    existing.add(normalized)
        return merged

    async def _load_keyword_overrides(
        self,
        *,
        tenant_id: UUID | None,
        db_session: Any = None,
    ) -> Dict[str, List[str]]:
        if tenant_id is None or db_session is None:
            return {}
        try:
            row = (
                await db_session.execute(
                    text(
                        """
                        SELECT extra
                        FROM operator_settings
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": str(tenant_id)},
                )
            ).fetchone()
        except (DBAPIError, ProgrammingError) as exc:
            logger.warning(
                "[DeterministicIntakePreFilter] override load failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return {}

        if not row:
            return {}
        extra = row[0] or {}
        if not isinstance(extra, dict):
            return {}
        overrides = extra.get("intent_classifier_keyword_overrides") or {}
        if not isinstance(overrides, dict):
            return {}
        normalized: Dict[str, List[str]] = {}
        for intent, values in overrides.items():
            if intent not in self.PATTERNS or not isinstance(values, list):
                continue
            normalized[intent] = [str(value).strip().lower() for value in values if str(value).strip()]
        return normalized

    def _to_message_classification(
        self,
        details: dict[str, Any],
        text: str,
    ) -> MessageClassification:
        legacy_intent = str(details["intent"])
        topic, intent_type, urgency, sub_intents = _legacy_to_brain_shape(
            legacy_intent,
            text,
        )
        matched_keyword = None
        score_map = details.get("scores") or {}
        if legacy_intent in score_map:
            matched_keyword = legacy_intent
        reason = (
            f"deterministic prefilter intent={legacy_intent} "
            f"confidence={float(details['confidence']):.2f}"
        )
        if details.get("contradictory_signals"):
            reason += " contradictory_signals=true"
        return MessageClassification(
            intent_type=intent_type,
            intent_topic=topic,
            sub_intents=sub_intents,
            confidence=float(details["confidence"]),
            urgency=urgency,
            requires_human_review=False,
            reason=reason,
            matched_keyword=matched_keyword,
            matched_route="deterministic_prefilter",
        )


def _coerce_tenant_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _legacy_to_brain_shape(
    legacy_intent: str,
    text: str,
) -> tuple[str, IntentType, Urgency, List[str]]:
    msg = (text or "").lower()
    if legacy_intent == "local_area":
        return "local_recommendation", IntentType.QUESTION, Urgency.LOW, ["local_area"]
    if legacy_intent == "pet_policy":
        return "house_rules", IntentType.QUESTION, Urgency.LOW, ["pet_policy", "policy_question"]
    if legacy_intent == "check_in_process":
        if any(pattern in msg for pattern in _CHECK_IN_TIMING_PATTERNS):
            return "late_checkout", IntentType.REQUEST, Urgency.MEDIUM, ["check_in_process"]
        if any(pattern in msg for pattern in _ACCESS_PATTERNS):
            return "access", IntentType.QUESTION, Urgency.MEDIUM, ["check_in_process"]
        return "late_checkout", IntentType.REQUEST, Urgency.MEDIUM, ["check_in_process"]
    if legacy_intent == "review_response" or any(pattern in msg for pattern in _REVIEW_PATTERNS):
        return "general", IntentType.QUESTION, Urgency.MEDIUM, ["review_response"]
    if legacy_intent == "general":
        return "general", IntentType.QUESTION, Urgency.MEDIUM, []
    return "booking_inquiry", IntentType.QUESTION, Urgency.MEDIUM, [legacy_intent]


def legacy_intent_from_classification(
    classification: MessageClassification,
    *,
    message_text: str = "",
) -> str:
    sub_intents = list(classification.sub_intents or [])
    if classification.intent_topic == "local_recommendation":
        return "local_area"
    if classification.intent_topic == "late_checkout":
        return "check_in_process"
    if classification.intent_topic == "access":
        return "check_in_process"
    if classification.intent_topic == "house_rules":
        if any(token in (message_text or "").lower() for token in _PET_PATTERNS):
            return "pet_policy"
        return "general"
    if classification.intent_topic == "booking_inquiry":
        for intent in (
            "pricing",
            "availability",
            "amenities",
            "group_size",
            "accessibility",
            "pet_policy",
            "check_in_process",
            "review_response",
        ):
            if intent in sub_intents:
                return intent
        if "discount" in sub_intents:
            return "pricing"
        if "sleeping_arrangement" in sub_intents:
            return "amenities"
        return "general"
    return "general"
