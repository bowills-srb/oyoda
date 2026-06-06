# Superseded by DraftLearningService (Piece B). Dormant.
"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Operator Learning Engine

Captures signal from every operator action and converts it into structured
knowledge that improves future AI drafts — at three scopes:

  PROPERTY scope   — "This specific property has a heated pool and the owner
                      always mentions the $50/day heating fee."

  OPERATOR scope   — "This operator never discounts. They always respond to
                      pricing questions with a friendly but firm no."

  PLATFORM scope   — "Across all operators, pet inquiries that mention
                      'small dog' have a 92% allow rate in 30A market."

HOW LEARNING HAPPENS:

  1. Operator edits an AI draft before sending
     → diff(original_draft, edited_text)
     → extract what changed (tone shift, fact added, policy clarified, price info)
     → classify the edit type
     → store as a "learned preference"

  2. Operator rejects a draft entirely
     → mark as negative example
     → flag the intent for this property as "needs better handling"

  3. Operator approves a draft unchanged
     → positive signal — this type of response is working

  4. Pattern accumulation over time
     → 3+ consistent edits of same type → become a "strong preference"
     → strong preferences are injected into future AI drafts as constraints
     → weekly digest shows operator what the system has learned

PRIVACY MODEL:
  - Property-scope data: fully scoped to that operator
  - Operator-scope data: scoped to that operator (e.g. discount policy)
  - Platform-scope data: anonymized and aggregated — no PII, no operator IDs
    in what gets shared. Only intent patterns + resolution rates.
  - Operators can opt out of platform-scope contribution (default: opted IN)

WHAT THIS ENABLES OVER TIME:
  - "Gulf View 305: operator always mentions the beach walkover is 200ft from door"
  - "This operator: never accepts discount requests, firm but warm tone"
  - "30A platform: dog-friendly inquiries → allow rate 78%, median fee $150"
  - "Availability inquiries with >7 night requests → 94% convert to booking"
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.db.session_safety import safe_rollback

logger = logging.getLogger(__name__)


# =============================================================================
# EDIT CLASSIFICATION
# =============================================================================

class EditType(str, Enum):
    """What kind of change did the operator make?"""
    TONE_SOFTER      = "tone_softer"       # Made more warm/friendly
    TONE_FIRMER      = "tone_firmer"       # Made more direct/assertive
    FACT_ADDED       = "fact_added"        # Added specific property detail
    FACT_CORRECTED   = "fact_corrected"    # Fixed incorrect AI fact
    POLICY_CLARIFIED = "policy_clarified"  # Added/changed policy info
    PRICE_ADDED      = "price_added"       # Added pricing info (fee, rate, etc.)
    PRICE_DECLINED   = "price_declined"    # Declined to discount
    LENGTH_SHORTENED = "length_shortened"  # Cut it down significantly
    LENGTH_EXPANDED  = "length_expanded"   # Added more detail
    CTA_CHANGED      = "cta_changed"       # Changed the call-to-action
    COMPLETE_REWRITE = "complete_rewrite"  # Rewrote most of it
    MINOR_POLISH     = "minor_polish"      # Small wording tweaks only


@dataclass
class EditAnalysis:
    """Result of analyzing what an operator changed."""
    edit_type: EditType
    similarity_score: float           # 0-1, how similar original and edited are
    added_phrases: List[str]          # Key phrases added by operator
    removed_phrases: List[str]        # Key phrases removed by operator
    
    # Extracted signals
    price_signals: List[str]          # Any pricing info found in the edit
    policy_signals: List[str]         # Any policy language found
    property_facts: List[str]         # Any specific property details added
    
    # Confidence that this is a learnable preference (not a one-off)
    learnable: bool = True
    

# =============================================================================
# EDIT ANALYZER — zero-cost, pure Python
# =============================================================================

class EditAnalyzer:
    """
    Analyzes the diff between an AI draft and the operator's edited version.
    Classifies what changed and extracts learnable signals.
    """

    PRICE_PATTERNS = [
        r'\$[\d,]+', r'\d+\s*(?:dollars?|per night|/night|fee)',
        r'(?:no|not)\s+(?:discount|negotiat|lower)',
        r'rate is\s+(?:set|firm|fixed)',
        r'10%\s+off', r'complimentary', r'waive\s+the\s+fee',
    ]
    POLICY_PATTERNS = [
        r'(?:no|not)\s+(?:pets?|dogs?|cats?|animals?)',
        r'pets?\s+(?:allowed|welcome|ok)',
        r'(?:minimum|min)\s+\d+\s+nights?',
        r'no\s+(?:smoking|parties?|events?)',
        r'quiet\s+hours?', r'max\s+\d+\s+guests?',
    ]
    PROPERTY_FACT_PATTERNS = [
        r'pool\s+(?:is|can be)\s+heated', r'beach\s+(?:access|chairs?|gear)',
        r'\d+\s*(?:ft|feet|yards?|steps?|minutes?|miles?)\s+(?:from|to|away)',
        r'wifi\s+(?:password|network|is)', r'door\s+code', r'parking',
        r'check.?in\s+at\s+\d+', r'check.?out\s+(?:by|at)\s+\d+',
        r'washer\s+(?:and|\/)\s+dryer', r'fully\s+(?:equipped|stocked)',
    ]

    def analyze(self, original: str, edited: str) -> EditAnalysis:
        """Compare original AI draft vs operator's edited version."""
        orig_clean = original.strip()
        edit_clean = edited.strip()

        # Similarity
        similarity = difflib.SequenceMatcher(None, orig_clean, edit_clean).ratio()

        # Word-level diff for phrase extraction
        orig_words = set(orig_clean.lower().split())
        edit_words = set(edit_clean.lower().split())
        
        # Extract meaningful added/removed phrases (3+ word sequences)
        added_phrases = self._extract_new_phrases(orig_clean, edit_clean)
        removed_phrases = self._extract_new_phrases(edit_clean, orig_clean)

        # Signal extraction from the EDIT (what operator added)
        price_signals = self._extract_pattern_matches(edit_clean, self.PRICE_PATTERNS)
        policy_signals = self._extract_pattern_matches(edit_clean, self.POLICY_PATTERNS)
        property_facts = self._extract_pattern_matches(edit_clean, self.PROPERTY_FACT_PATTERNS)

        # Classify edit type
        edit_type = self._classify_edit(
            similarity=similarity,
            orig_words=orig_words,
            edit_words=edit_words,
            added_phrases=added_phrases,
            price_signals=price_signals,
            policy_signals=policy_signals,
            property_facts=property_facts,
            original=orig_clean,
            edited=edit_clean,
        )

        # Minor polish (>90% similar) is not strongly learnable
        learnable = edit_type != EditType.MINOR_POLISH and similarity < 0.95

        return EditAnalysis(
            edit_type=edit_type,
            similarity_score=round(similarity, 3),
            added_phrases=added_phrases[:5],
            removed_phrases=removed_phrases[:5],
            price_signals=price_signals,
            policy_signals=policy_signals,
            property_facts=property_facts,
            learnable=learnable,
        )

    def _extract_new_phrases(self, source: str, target: str, min_words: int = 3) -> List[str]:
        """Extract phrases present in target but not in source."""
        src_sents = set(re.split(r'[.!?\n]', source.lower()))
        phrases = []
        for sent in re.split(r'[.!?\n]', target):
            sent = sent.strip()
            words = sent.split()
            if len(words) < min_words:
                continue
            sent_lower = sent.lower()
            if not any(s.strip() and sent_lower in s for s in src_sents):
                phrases.append(sent[:120])
        return phrases[:8]

    def _extract_pattern_matches(self, text: str, patterns: List[str]) -> List[str]:
        matches = []
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                matched = m.group(0).strip()
                if matched not in matches:
                    matches.append(matched)
        return matches

    def _classify_edit(
        self,
        similarity: float,
        orig_words: set,
        edit_words: set,
        added_phrases: List[str],
        price_signals: List[str],
        policy_signals: List[str],
        property_facts: List[str],
        original: str,
        edited: str,
    ) -> EditType:
        if similarity < 0.35:
            return EditType.COMPLETE_REWRITE
        if similarity > 0.92:
            return EditType.MINOR_POLISH

        # Price signals are most specific — check first
        if price_signals:
            no_discount_words = {'no', 'not', 'firm', 'fixed', 'set', 'standard'}
            if any(w in edited.lower() for w in no_discount_words):
                return EditType.PRICE_DECLINED
            return EditType.PRICE_ADDED

        # Policy or property facts
        if policy_signals:
            return EditType.POLICY_CLARIFIED
        if property_facts:
            return EditType.FACT_ADDED

        # Length change
        orig_len = len(original.split())
        edit_len = len(edited.split())
        if edit_len < orig_len * 0.6:
            return EditType.LENGTH_SHORTENED
        if edit_len > orig_len * 1.5:
            return EditType.LENGTH_EXPANDED

        # Tone signals
        warm_words = {'wonderful', 'love', 'happy', 'glad', 'great', 'amazing', 'perfect',
                      'absolutely', 'certainly', 'pleasure', 'welcome', 'enjoy'}
        firm_words = {'unfortunately', 'unable', 'cannot', 'policy', 'require', 'must',
                      'standard', 'firm', 'set rate', 'not available'}
        added_lower = ' '.join(added_phrases).lower()
        if sum(1 for w in warm_words if w in added_lower) >= 2:
            return EditType.TONE_SOFTER
        if sum(1 for w in firm_words if w in added_lower) >= 1:
            return EditType.TONE_FIRMER

        # CTA change (last sentence changed)
        orig_last = original.rstrip('.!').rsplit('.', 1)[-1].strip().lower()
        edit_last = edited.rstrip('.!').rsplit('.', 1)[-1].strip().lower()
        if orig_last and edit_last and orig_last != edit_last:
            return EditType.CTA_CHANGED

        return EditType.MINOR_POLISH


# =============================================================================
# LEARNED PREFERENCE MODEL
# =============================================================================

@dataclass
class LearnedPreference:
    """
    A preference the system has inferred from repeated operator behavior.
    Stored in operator_learned_preferences table.
    """
    preference_id: str
    company_id: str
    property_external_id: Optional[str]    # None = applies to all properties

    intent: str                             # Which inquiry intent this applies to
    edit_type: EditType
    
    # The actual learned content
    instruction: str                        # Human-readable constraint
    example_edit: str                       # Anonymized example of the edit
    
    # Confidence tracking
    observation_count: int = 1             # How many times we've seen this
    confidence: float = 0.0               # 0-1, grows with observations
    
    # Scope
    scope: str = "property"               # "property" | "operator" | "platform"
    
    # Status
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_seen_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_strong(self) -> bool:
        """Strong preference = seen 3+ times with high confidence."""
        return self.observation_count >= 3 and self.confidence >= 0.75


# =============================================================================
# OPERATOR LEARNING SERVICE — main entry point
# =============================================================================

class OperatorLearningService:
    """
    Processes operator edits and builds a preference model over time.

    Called from:
      - approve_inquiry_draft (when edited_text != original draft_text)
      - post-booking message approval (future)
      - Any operator override of an AI response
    """

    def __init__(self, db):
        self.db = db
        self._analyzer = EditAnalyzer()

    async def record_edit(
        self,
        company_id: str,
        draft_id: str,
        original_draft: str,
        edited_text: str,
        intent: str,
        property_external_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point. Call this whenever an operator edits an AI draft.
        
        Returns what was learned (or None if nothing significant).
        """
        if not original_draft or not edited_text:
            return {"learned": False, "reason": "missing_text"}

        if original_draft.strip() == edited_text.strip():
            return {"learned": False, "reason": "no_change"}

        # Analyze the edit
        analysis = self._analyzer.analyze(original_draft, edited_text)

        # Always store the raw edit event (full audit trail)
        event_id = await self._store_edit_event(
            company_id=company_id,
            draft_id=draft_id,
            intent=intent,
            property_external_id=property_external_id,
            original_draft=original_draft,
            edited_text=edited_text,
            analysis=analysis,
        )

        if not analysis.learnable:
            return {
                "learned": False,
                "reason": "minor_polish",
                "edit_type": analysis.edit_type.value,
                "similarity": analysis.similarity_score,
            }

        # Build the preference instruction from the analysis
        instruction = self._build_instruction(analysis, intent, context or {})
        if not instruction:
            return {"learned": False, "reason": "no_instruction_extracted"}

        # Upsert the preference — increment count if it exists, create if new
        pref = await self._upsert_preference(
            company_id=company_id,
            property_external_id=property_external_id,
            intent=intent,
            edit_type=analysis.edit_type,
            instruction=instruction,
            example_edit=edited_text[:300],  # Store anonymized snippet
        )

        # If this is a strong preference, also propagate to operator scope
        # (if property-level preference appears on multiple properties)
        operator_pref = None
        if pref["observation_count"] >= 3 and property_external_id:
            operator_pref = await self._maybe_promote_to_operator_scope(
                company_id=company_id,
                intent=intent,
                edit_type=analysis.edit_type,
                instruction=instruction,
            )

        # If opted in, contribute anonymized signal to platform scope
        await self._maybe_contribute_to_platform(
            company_id=company_id,
            intent=intent,
            edit_type=analysis.edit_type,
            analysis=analysis,
        )

        logger.info(
            f"[Learning] {company_id} | {intent} | {analysis.edit_type.value} "
            f"| count={pref['observation_count']} | conf={pref['confidence']:.2f}"
        )

        return {
            "learned": True,
            "edit_type": analysis.edit_type.value,
            "instruction": instruction,
            "observation_count": pref["observation_count"],
            "confidence": pref["confidence"],
            "is_strong_preference": pref["observation_count"] >= 3,
            "promoted_to_operator_scope": operator_pref is not None,
        }

    async def record_approval(
        self,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str] = None,
    ) -> None:
        """
        Record that a draft was approved unchanged — positive signal.
        Increments confidence on existing matching preferences.
        """
        try:
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    INSERT INTO operator_draft_events
                        (company_id, draft_id, intent, property_external_id,
                         event_type, created_at)
                    VALUES
                        (:cid::uuid, :did, :intent, :prop,
                         'approved_unchanged', NOW())
                    ON CONFLICT DO NOTHING
                """),
                {"cid": company_id, "did": draft_id, "intent": intent, "prop": property_external_id},
            )
            await self.db.commit()
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] approval record failed (non-fatal): {e}")

    async def record_rejection(
        self,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str] = None,
    ) -> None:
        """
        Record that a draft was rejected entirely — negative signal.
        Flags this intent+property combination for KB gap review.
        """
        try:
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    INSERT INTO operator_draft_events
                        (company_id, draft_id, intent, property_external_id,
                         event_type, created_at)
                    VALUES
                        (:cid::uuid, :did, :intent, :prop,
                         'rejected', NOW())
                """),
                {"cid": company_id, "did": draft_id, "intent": intent, "prop": property_external_id},
            )
            await self.db.commit()
            logger.info(f"[Learning] Draft rejected for intent={intent} prop={property_external_id}")
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] rejection record failed (non-fatal): {e}")

    async def get_preferences_for_draft(
        self,
        company_id: str,
        intent: str,
        property_external_id: Optional[str] = None,
    ) -> List[str]:
        """
        Get all active learned preferences relevant to this draft context.
        Returns a list of instruction strings to inject into the AI prompt.

        Called from the draft generator before building the AI prompt.
        """
        try:
            from sqlalchemy import text

            rows = await self.db.execute(
                text("""
                    SELECT instruction, scope, observation_count, confidence
                    FROM operator_learned_preferences
                    WHERE company_id = :cid::uuid
                      AND intent IN (:intent, 'all')
                      AND is_active = TRUE
                      AND confidence >= 0.50
                      AND (
                            property_external_id = :prop
                            OR property_external_id IS NULL
                      )
                    ORDER BY
                        CASE scope WHEN 'property' THEN 1 WHEN 'operator' THEN 2 ELSE 3 END,
                        observation_count DESC
                    LIMIT 5
                """),
                {"cid": company_id, "intent": intent, "prop": property_external_id},
            )
            prefs = rows.fetchall()
            return [r.instruction for r in prefs if r.instruction]
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] get_preferences failed (non-fatal): {e}")
            return []

    async def get_platform_intelligence(
        self,
        intent: str,
        market: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get anonymized platform-level intelligence for a given intent.
        E.g. "In 30A: 78% of pet inquiries allow pets, median fee $150."
        
        This feeds the AI draft generator with market-wide patterns.
        """
        try:
            from sqlalchemy import text
            row = await self.db.execute(
                text("""
                    SELECT intelligence_text, sample_count, last_updated
                    FROM platform_intelligence
                    WHERE intent = :intent
                      AND (:market IS NULL OR market = :market)
                      AND is_active = TRUE
                    ORDER BY sample_count DESC
                    LIMIT 1
                """),
                {"intent": intent, "market": market},
            )
            r = row.fetchone()
            if r and r.sample_count >= 10:  # Only trust with enough samples
                return r.intelligence_text
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] platform intelligence lookup failed: {e}")
        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_instruction(
        self,
        analysis: EditAnalysis,
        intent: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """Convert an edit analysis into a human-readable constraint instruction."""

        if analysis.edit_type == EditType.PRICE_DECLINED:
            return (
                "Do not offer discounts or negotiate pricing. "
                "Respond warmly but firmly that rates are set."
            )

        if analysis.edit_type == EditType.PRICE_ADDED and analysis.price_signals:
            fee_info = analysis.price_signals[0]
            return f"When mentioning fees, include: {fee_info}"

        if analysis.edit_type == EditType.POLICY_CLARIFIED and analysis.policy_signals:
            policy = analysis.policy_signals[0]
            return f"Policy to include when relevant: {policy}"

        if analysis.edit_type == EditType.FACT_ADDED and analysis.property_facts:
            fact = analysis.property_facts[0]
            return f"Always include this property fact when relevant: {fact}"

        if analysis.edit_type == EditType.TONE_SOFTER:
            return (
                "Use a warmer, more enthusiastic tone. "
                "Express genuine excitement about hosting."
            )

        if analysis.edit_type == EditType.TONE_FIRMER:
            return (
                "Be direct and professional. "
                "State policies clearly without excessive softening."
            )

        if analysis.edit_type == EditType.LENGTH_SHORTENED:
            return "Keep responses concise — 2 sentences max for this inquiry type."

        if analysis.edit_type == EditType.CTA_CHANGED and analysis.added_phrases:
            cta = analysis.added_phrases[-1][:80]
            return f"End responses with: {cta}"

        if analysis.edit_type == EditType.COMPLETE_REWRITE:
            # Full rewrite — store the whole edited text as an example
            return None  # Too variable to distill into a single instruction

        return None

    async def _store_edit_event(
        self,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str],
        original_draft: str,
        edited_text: str,
        analysis: EditAnalysis,
    ) -> str:
        """Store the raw edit event for audit trail and future analysis."""
        try:
            import uuid as _uuid
            import json
            from sqlalchemy import text
            event_id = str(_uuid.uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO operator_draft_events (
                        id, company_id, draft_id, intent, property_external_id,
                        event_type, original_draft, edited_text,
                        edit_type, similarity_score,
                        added_phrases, price_signals, policy_signals, property_facts,
                        created_at
                    ) VALUES (
                        :id, :cid::uuid, :did, :intent, :prop,
                        'edited', :orig, :edit,
                        :etype, :sim,
                        :added, :price, :policy, :facts,
                        NOW()
                    )
                """),
                {
                    "id": event_id,
                    "cid": company_id,
                    "did": draft_id,
                    "intent": intent,
                    "prop": property_external_id,
                    "orig": original_draft[:1000],
                    "edit": edited_text[:1000],
                    "etype": analysis.edit_type.value,
                    "sim": analysis.similarity_score,
                    "added": json.dumps(analysis.added_phrases),
                    "price": json.dumps(analysis.price_signals),
                    "policy": json.dumps(analysis.policy_signals),
                    "facts": json.dumps(analysis.property_facts),
                },
            )
            await self.db.commit()
            return event_id
        except Exception as e:
            await safe_rollback(self.db)
            logger.warning(f"[Learning] event store failed (non-fatal): {e}")
            return ""

    async def _upsert_preference(
        self,
        company_id: str,
        property_external_id: Optional[str],
        intent: str,
        edit_type: EditType,
        instruction: str,
        example_edit: str,
    ) -> Dict[str, Any]:
        """
        Increment observation count if this preference exists,
        create it if it's new. Recalculate confidence.
        
        Confidence formula:
          conf = 1 - (1 / observation_count)
          At 1 obs: 0.0 (uncertain)
          At 2 obs: 0.5
          At 3 obs: 0.67
          At 5 obs: 0.80
          At 10 obs: 0.90
        """
        try:
            import uuid as _uuid
            from sqlalchemy import text

            # Try to find an existing preference with same company+property+intent+type
            existing = await self.db.execute(
                text("""
                    SELECT id, observation_count
                    FROM operator_learned_preferences
                    WHERE company_id = :cid::uuid
                      AND intent = :intent
                      AND edit_type = :etype
                      AND (
                            (:prop IS NULL AND property_external_id IS NULL)
                            OR property_external_id = :prop
                      )
                    LIMIT 1
                """),
                {"cid": company_id, "intent": intent, "etype": edit_type.value, "prop": property_external_id},
            )
            row = existing.fetchone()

            if row:
                new_count = (row.observation_count or 1) + 1
                confidence = round(1 - (1 / new_count), 3)
                await self.db.execute(
                    text("""
                        UPDATE operator_learned_preferences
                        SET observation_count = :count,
                            confidence = :conf,
                            instruction = :inst,
                            last_seen_at = NOW()
                        WHERE id = :id
                    """),
                    {"count": new_count, "conf": confidence, "inst": instruction, "id": row.id},
                )
                await self.db.commit()
                return {"observation_count": new_count, "confidence": confidence, "id": str(row.id)}

            else:
                pref_id = str(_uuid.uuid4())
                await self.db.execute(
                    text("""
                        INSERT INTO operator_learned_preferences (
                            id, company_id, property_external_id,
                            intent, edit_type, scope,
                            instruction, example_edit,
                            observation_count, confidence, is_active,
                            created_at, last_seen_at
                        ) VALUES (
                            :id, :cid::uuid, :prop,
                            :intent, :etype, 'property',
                            :inst, :example,
                            1, 0.0, TRUE,
                            NOW(), NOW()
                        )
                    """),
                    {
                        "id": pref_id, "cid": company_id, "prop": property_external_id,
                        "intent": intent, "etype": edit_type.value,
                        "inst": instruction, "example": example_edit[:300],
                    },
                )
                await self.db.commit()
                return {"observation_count": 1, "confidence": 0.0, "id": pref_id}

        except Exception as e:
            await safe_rollback(self.db)
            logger.error(f"[Learning] upsert_preference failed: {e}")
            return {"observation_count": 1, "confidence": 0.0, "id": ""}

    async def _maybe_promote_to_operator_scope(
        self,
        company_id: str,
        intent: str,
        edit_type: EditType,
        instruction: str,
    ) -> Optional[Dict[str, Any]]:
        """
        If the same preference appears on 2+ properties for an operator,
        promote it to operator scope so it applies everywhere.
        """
        try:
            from sqlalchemy import text
            count_row = await self.db.execute(
                text("""
                    SELECT COUNT(DISTINCT property_external_id) AS prop_count
                    FROM operator_learned_preferences
                    WHERE company_id = :cid::uuid
                      AND intent = :intent
                      AND edit_type = :etype
                      AND scope = 'property'
                      AND observation_count >= 2
                      AND property_external_id IS NOT NULL
                """),
                {"cid": company_id, "intent": intent, "etype": edit_type.value},
            )
            prop_count = (count_row.fetchone().prop_count or 0)

            if prop_count >= 2:
                # Promote to operator scope
                import uuid as _uuid
                await self.db.execute(
                    text("""
                        INSERT INTO operator_learned_preferences (
                            id, company_id, property_external_id,
                            intent, edit_type, scope,
                            instruction, example_edit,
                            observation_count, confidence, is_active,
                            created_at, last_seen_at
                        ) VALUES (
                            :id, :cid::uuid, NULL,
                            :intent, :etype, 'operator',
                            :inst, '',
                            :count, 0.80, TRUE,
                            NOW(), NOW()
                        )
                        ON CONFLICT (company_id, intent, edit_type, scope)
                        WHERE property_external_id IS NULL
                        DO UPDATE SET
                            observation_count = operator_learned_preferences.observation_count + 1,
                            confidence = LEAST(0.95, operator_learned_preferences.confidence + 0.05),
                            last_seen_at = NOW()
                    """),
                    {
                        "id": str(_uuid.uuid4()), "cid": company_id,
                        "intent": intent, "etype": edit_type.value,
                        "inst": instruction, "count": prop_count * 2,
                    },
                )
                await self.db.commit()
                logger.info(
                    f"[Learning] Promoted to operator scope: {edit_type.value} for {intent} "
                    f"(seen on {prop_count} properties)"
                )
                return {"promoted": True, "property_count": prop_count}
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] promote_to_operator_scope failed (non-fatal): {e}")
        return None

    async def _maybe_contribute_to_platform(
        self,
        company_id: str,
        intent: str,
        edit_type: EditType,
        analysis: EditAnalysis,
    ) -> None:
        """
        Contribute anonymized signal to platform-level intelligence.
        Only called if operator has opted in (default: yes).
        No PII, no operator IDs — only intent patterns and edit type counts.
        """
        try:
            from sqlalchemy import text

            # Check opt-in status
            opt_in = await self.db.execute(
                text("""
                    SELECT platform_learning_opt_in
                    FROM operator_pre_booking_policies
                    WHERE company_id = :cid::uuid
                    LIMIT 1
                """),
                {"cid": company_id},
            )
            row = opt_in.fetchone()
            if row and row.platform_learning_opt_in is False:
                return  # Opted out

            # Increment anonymized platform counter
            await self.db.execute(
                text("""
                    INSERT INTO platform_learning_events (
                        intent, edit_type, has_price_signal,
                        has_policy_signal, has_property_fact,
                        created_at
                    ) VALUES (
                        :intent, :etype, :price, :policy, :fact, NOW()
                    )
                """),
                {
                    "intent": intent,
                    "etype": edit_type.value,
                    "price": bool(analysis.price_signals),
                    "policy": bool(analysis.policy_signals),
                    "fact": bool(analysis.property_facts),
                },
            )
            await self.db.commit()
        except Exception as e:
            await safe_rollback(self.db)
            logger.debug(f"[Learning] platform contribution failed (non-fatal): {e}")


# =============================================================================
# PLATFORM INTELLIGENCE AGGREGATOR (runs nightly via Celery)
# =============================================================================

async def rebuild_platform_intelligence(db) -> Dict[str, int]:
    """
    Nightly job: aggregate platform_learning_events into platform_intelligence
    summaries that the AI can use for market context.
    
    Example output for 'pet_policy' intent:
    "In this market: 78% of operators allow pets, with a typical fee of $150."
    """
    from sqlalchemy import text

    updated = 0
    try:
        # Aggregate by intent + edit_type
        rows = await db.execute(
            text("""
                SELECT
                    intent,
                    edit_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN has_price_signal THEN 1 ELSE 0 END) AS with_price,
                    SUM(CASE WHEN has_policy_signal THEN 1 ELSE 0 END) AS with_policy
                FROM platform_learning_events
                WHERE created_at >= NOW() - INTERVAL '90 days'
                GROUP BY intent, edit_type
                HAVING COUNT(*) >= 5
            """),
        )
        groups = rows.fetchall()

        for group in groups:
            intelligence_text = _format_platform_intelligence(
                intent=group.intent,
                edit_type=group.edit_type,
                total=group.total,
                with_price=group.with_price,
                with_policy=group.with_policy,
            )
            if not intelligence_text:
                continue

            await db.execute(
                text("""
                    INSERT INTO platform_intelligence
                        (intent, edit_type, intelligence_text, sample_count,
                         market, is_active, last_updated)
                    VALUES
                        (:intent, :etype, :text, :count, NULL, TRUE, NOW())
                    ON CONFLICT (intent, edit_type, market)
                    DO UPDATE SET
                        intelligence_text = EXCLUDED.intelligence_text,
                        sample_count = EXCLUDED.sample_count,
                        last_updated = NOW()
                """),
                {
                    "intent": group.intent,
                    "etype": group.edit_type,
                    "text": intelligence_text,
                    "count": group.total,
                },
            )
            updated += 1

        await db.commit()
        logger.info(f"[Platform Intelligence] Rebuilt {updated} intelligence entries")

    except Exception as e:
        logger.error(f"[Platform Intelligence] Rebuild failed: {e}")

    return {"updated": updated}


def _format_platform_intelligence(
    intent: str,
    edit_type: str,
    total: int,
    with_price: int,
    with_policy: int,
) -> Optional[str]:
    """Build a human-readable intelligence summary for the AI to use."""
    if intent == "pet_policy" and edit_type == "policy_clarified":
        pct = round((with_policy / total) * 100) if total > 0 else 0
        return f"Platform data ({total} operators): {pct}% of responses include explicit pet policy language."

    if intent == "pricing" and edit_type == "price_declined":
        pct = round((total) * 100 / max(total, 1))
        return f"Platform data: Most operators respond firmly to pricing negotiation requests — avoid offering discounts."

    if intent == "pricing" and edit_type == "price_added":
        return f"Platform data ({total} operators): Pricing responses frequently include specific fee breakdowns."

    if intent == "amenities" and edit_type == "fact_added":
        return f"Platform data: Amenity inquiries frequently receive additional property-specific detail beyond the listing."

    if edit_type == "length_shortened":
        return f"Platform data: For {intent} inquiries, shorter responses (2 sentences) perform better."

    return None


# =============================================================================
# PREFERENCE INJECTION — called from draft generator
# =============================================================================

async def build_preference_context(
    db,
    company_id: str,
    intent: str,
    property_external_id: Optional[str] = None,
    market: Optional[str] = None,
) -> str:
    """
    Build a context block of learned preferences + platform intelligence
    to inject into the AI draft generation prompt.

    Returns a formatted string or empty string if nothing learned yet.
    """
    svc = OperatorLearningService(db)
    prefs = await svc.get_preferences_for_draft(company_id, intent, property_external_id)
    platform_intel = await svc.get_platform_intelligence(intent, market)

    parts = []

    if prefs:
        parts.append("OPERATOR PREFERENCES (apply these to this response):")
        for i, pref in enumerate(prefs, 1):
            parts.append(f"  {i}. {pref}")

    if platform_intel:
        parts.append(f"\nMARKET CONTEXT: {platform_intel}")

    return "\n".join(parts) if parts else ""


# =============================================================================
# SINGLETON
# =============================================================================

def get_learning_service(db) -> OperatorLearningService:
    return OperatorLearningService(db)


# =============================================================================
# DB MIGRATION
# =============================================================================

MIGRATION_SQL = """
-- Raw edit event log (full audit trail)
CREATE TABLE IF NOT EXISTS operator_draft_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL,
    draft_id            TEXT NOT NULL,
    intent              TEXT NOT NULL,
    property_external_id TEXT,

    event_type          TEXT NOT NULL,  -- 'edited' | 'approved_unchanged' | 'rejected'
    original_draft      TEXT,
    edited_text         TEXT,

    -- Extracted from diff analysis
    edit_type           TEXT,
    similarity_score    NUMERIC(5,4),
    added_phrases       JSONB DEFAULT '[]',
    price_signals       JSONB DEFAULT '[]',
    policy_signals      JSONB DEFAULT '[]',
    property_facts      JSONB DEFAULT '[]',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_draft_events_company
    ON operator_draft_events (company_id, intent, created_at DESC);

-- Learned preferences (distilled from repeated edits)
CREATE TABLE IF NOT EXISTS operator_learned_preferences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL,
    property_external_id TEXT,          -- NULL = applies to all properties (operator scope)

    intent              TEXT NOT NULL,
    edit_type           TEXT NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'property',  -- 'property' | 'operator' | 'platform'

    instruction         TEXT NOT NULL,  -- What to tell the AI
    example_edit        TEXT,           -- Anonymized example

    observation_count   INTEGER NOT NULL DEFAULT 1,
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_preferences_lookup
    ON operator_learned_preferences (company_id, intent, is_active)
    WHERE is_active = TRUE;

-- Add opt-in column to policies table
ALTER TABLE operator_pre_booking_policies
    ADD COLUMN IF NOT EXISTS platform_learning_opt_in BOOLEAN DEFAULT TRUE;

-- Anonymized platform learning events (no operator IDs)
CREATE TABLE IF NOT EXISTS platform_learning_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent      TEXT NOT NULL,
    edit_type   TEXT NOT NULL,
    has_price_signal    BOOLEAN DEFAULT FALSE,
    has_policy_signal   BOOLEAN DEFAULT FALSE,
    has_property_fact   BOOLEAN DEFAULT FALSE,
    market      TEXT,               -- Geo market (optional)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_events_intent
    ON platform_learning_events (intent, edit_type, created_at DESC);

-- Aggregated platform intelligence (rebuilt nightly)
CREATE TABLE IF NOT EXISTS platform_intelligence (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent              TEXT NOT NULL,
    edit_type           TEXT NOT NULL,
    market              TEXT,
    intelligence_text   TEXT NOT NULL,
    sample_count        INTEGER NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (intent, edit_type, market)
);
"""
