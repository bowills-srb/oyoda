"""autonomy_score_service — directional autonomy posture.

Computes a v1 directional score (0..1) from real aggregate signals:
  - Readiness component:  KB coverage vs gaps relative to property count.
  - Escalation component: resolved pressure in the last 30 days.
  - Behavior component:   NEUTRAL constant (decoupled from learning redesign).

Output is POSTURE, not precision. Do not present to operators as a hard
percentage without appropriate hedging language.

Named constants are intentionally coarse defaults. Tune against real
Beach Habitats data once the trend has accumulated enough points.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.gap_recorder import (
    normalize_question_key,
)
from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    get_dashboard_kb_service,
)
from db.models.concierge_knowledge import ConciergeKnowledgeGapModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable weight constants
# ---------------------------------------------------------------------------
WEIGHT_READINESS: float = 0.6
WEIGHT_ESCALATION: float = 0.3
WEIGHT_BEHAVIOR: float = 0.1

# Readiness sub-parameters
TARGET_KB_ENTRIES_PER_PROPERTY: int = 5   # "well-documented" threshold
READINESS_GAP_RATIO_HALF_SATURATION: float = 2.0
READINESS_GAP_PENALTY_WEIGHT: float = 0.6

# Escalation sub-parameters
TRAFFIC_SIGNAL_SESSION_THRESHOLD: int = 10
PRISTINE_ESCALATION_SCORE: float = 0.85

# Behavior is deliberately neutral until the learning layer ships
NEUTRAL_BEHAVIOR: float = 0.5

# Domain band cutoffs (Inquiry domain, portfolio-level proxy for v1)
BAND_AUTONOMOUS: float = 0.75
BAND_DEVELOPING: float = 0.45
# < BAND_DEVELOPING → Emerging


def _inquiry_band(score: float) -> str:
    """Map a 0..1 score to an autonomy band word."""
    if score >= BAND_AUTONOMOUS:
        return "Autonomous"
    if score >= BAND_DEVELOPING:
        return "Developing"
    return "Emerging"


async def _scalar_or(
    session: AsyncSession,
    default: Any,
    sql: str,
    params: Dict[str, Any],
) -> Any:
    """Execute a scalar query; return *default* on any exception."""
    try:
        result = await session.scalar(text(sql), params)
        return result if result is not None else default
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutonomyScore] scalar fallback (default=%s): %s", default, exc)
        try:
            await session.rollback()
        except Exception:
            pass
    return default


async def _count_distinct_genuine_attributed_gaps(
    session: AsyncSession,
    tenant_id: str,
) -> int:
    """
    Count unresolved knowledge gaps that are:
      - property-attributed (`property_id` present)
      - genuine failure signals (low/null confidence and no KB help or deflection)
      - distinct by (property_id, normalized question key)
    """
    rows = (
        await session.execute(
            select(
                ConciergeKnowledgeGapModel.property_id,
                ConciergeKnowledgeGapModel.question_text,
                ConciergeKnowledgeGapModel.confidence_score,
                ConciergeKnowledgeGapModel.metadata_json,
            ).where(
                ConciergeKnowledgeGapModel.tenant_id == uuid.UUID(tenant_id),
                ConciergeKnowledgeGapModel.resolved.is_(False),
                ConciergeKnowledgeGapModel.property_id.is_not(None),
            )
        )
    ).all()

    distinct_keys: set[tuple[str, str]] = set()
    for property_id, question_text, confidence_score, metadata in rows:
        meta = metadata if isinstance(metadata, dict) else {}
        used_kb_chunks = bool(meta.get("used_kb_chunks"))
        was_deflected = bool(meta.get("was_deflected"))
        is_genuine = (
            (confidence_score is None or float(confidence_score) < 0.5)
            and (not used_kb_chunks or was_deflected)
        )
        if not is_genuine:
            continue
        normalized_key = normalize_question_key(question_text or "")
        if not normalized_key:
            continue
        distinct_keys.add((str(property_id), normalized_key))
    return len(distinct_keys)


async def _distinct_genuine_gap_counts_by_property(
    session: AsyncSession,
    tenant_id: str,
) -> Dict[str, int]:
    """
    Return per-property unresolved knowledge-gap counts using the recorder's
    normalized question key so portfolio and per-property views dedupe the same
    way.
    """
    rows = (
        await session.execute(
            select(
                ConciergeKnowledgeGapModel.property_id,
                ConciergeKnowledgeGapModel.question_text,
                ConciergeKnowledgeGapModel.confidence_score,
                ConciergeKnowledgeGapModel.metadata_json,
            ).where(
                ConciergeKnowledgeGapModel.tenant_id == uuid.UUID(tenant_id),
                ConciergeKnowledgeGapModel.resolved.is_(False),
                ConciergeKnowledgeGapModel.property_id.is_not(None),
            )
        )
    ).all()

    distinct_keys: set[tuple[str, str]] = set()
    for property_id, question_text, confidence_score, metadata in rows:
        meta = metadata if isinstance(metadata, dict) else {}
        used_kb_chunks = bool(meta.get("used_kb_chunks"))
        was_deflected = bool(meta.get("was_deflected"))
        is_genuine = (
            (confidence_score is None or float(confidence_score) < 0.5)
            and (not used_kb_chunks or was_deflected)
        )
        if not is_genuine:
            continue
        normalized_key = normalize_question_key(question_text or "")
        if not normalized_key:
            continue
        distinct_keys.add((str(property_id), normalized_key))

    counts: dict[str, int] = defaultdict(int)
    for property_id, _normalized_key in distinct_keys:
        counts[property_id] += 1
    return dict(counts)


async def _count_recent_guest_sessions(
    session: AsyncSession,
    tenant_id: str,
) -> int:
    return int(
        await _scalar_or(
            session,
            0,
            """
            SELECT COUNT(*)
            FROM concierge_guest_sessions
            WHERE tenant_id = CAST(:tid AS uuid)
              AND created_at >= NOW() - INTERVAL '90 days'
            """,
            {"tid": tenant_id},
        )
        or 0
    )


def _readiness_score(
    *,
    property_count: int,
    kb_entries: int,
    distinct_gaps: int,
) -> float:
    """
    Readiness = saturated coverage multiplied by a smooth, scale-aware
    gap-burden penalty.

    Coverage saturation at 1.0 is intentional for v1: once a portfolio is
    "well documented", additional entries should not dominate the score.
    What needs to stay responsive is the penalty side, which now scales by
    gaps per property instead of flattening after ~10 raw rows.
    """
    target = max(1, property_count) * TARGET_KB_ENTRIES_PER_PROPERTY
    raw_coverage = min(1.0, (kb_entries or 0) / target)
    gap_ratio = (distinct_gaps or 0) / max(1, property_count)
    gap_penalty = gap_ratio / (gap_ratio + READINESS_GAP_RATIO_HALF_SATURATION)
    readiness = raw_coverage * (1.0 - READINESS_GAP_PENALTY_WEIGHT * gap_penalty)
    return round(max(0.0, min(1.0, readiness)), 4)


def _escalation_score(
    *,
    open_count: int,
    resolved_count: int,
    recent_session_count: int,
) -> float:
    """
    Distinguish:
      - active traffic + zero escalations: positive/pristine
      - some escalations: resolved ratio
      - no traffic + no escalations: neutral/insufficient signal
    """
    total = max(0, open_count) + max(0, resolved_count)
    if total > 0:
        return round(max(0.0, min(1.0, resolved_count / total)), 4)
    if recent_session_count >= TRAFFIC_SIGNAL_SESSION_THRESHOLD:
        return PRISTINE_ESCALATION_SCORE
    return NEUTRAL_BEHAVIOR


def _compute_portfolio_score_from_inputs(
    *,
    property_count: int,
    kb_entries: int,
    distinct_gaps: int,
    escalation_open: int,
    escalation_resolved: int,
    recent_session_count: int,
) -> Dict[str, float]:
    readiness = _readiness_score(
        property_count=property_count,
        kb_entries=kb_entries,
        distinct_gaps=distinct_gaps,
    )
    escalation = _escalation_score(
        open_count=escalation_open,
        resolved_count=escalation_resolved,
        recent_session_count=recent_session_count,
    )
    behavior = NEUTRAL_BEHAVIOR
    portfolio = (
        WEIGHT_READINESS * readiness
        + WEIGHT_ESCALATION * escalation
        + WEIGHT_BEHAVIOR * behavior
    )
    return {
        "readiness": round(readiness, 4),
        "escalation": round(escalation, 4),
        "behavior": round(behavior, 4),
        "portfolio": round(max(0.0, min(1.0, portfolio)), 4),
    }


def _property_snapshot_from_inputs(
    *,
    property_id: str,
    property_code: str | None,
    traffic_count: int,
    kb_entries: int,
    distinct_gaps: int,
    shared_escalation_open: int,
    shared_escalation_resolved: int,
    shared_recent_session_count: int,
) -> Dict[str, Any]:
    """
    Compute the Inquiry-domain posture for one property.

    If a property has no traffic, the honest answer is "Insufficient Signal"
    rather than a fabricated autonomy number.
    """
    normalized_code = str(property_code or "").strip() or None
    if int(traffic_count or 0) <= 0:
        return {
            "property_id": property_id,
            "property_code": normalized_code,
            "signal_status": "insufficient_signal",
            "domain_bands": {
                "inquiry": {"score": None, "band": "Insufficient Signal"},
                "guest_ops": "Developing",
                "maintenance": "Emerging",
                "turnover": "Emerging",
            },
            "components": {"behavior": "neutral"},
            "metrics": {
                "traffic_count": int(traffic_count or 0),
                "kb_entries": int(kb_entries or 0),
                "distinct_gaps": int(distinct_gaps or 0),
            },
        }

    scores = _compute_portfolio_score_from_inputs(
        property_count=1,
        kb_entries=int(kb_entries or 0),
        distinct_gaps=int(distinct_gaps or 0),
        escalation_open=int(shared_escalation_open or 0),
        escalation_resolved=int(shared_escalation_resolved or 0),
        recent_session_count=int(shared_recent_session_count or 0),
    )
    inquiry_score = scores["readiness"]
    return {
        "property_id": property_id,
        "property_code": normalized_code,
        "signal_status": "computed",
        "domain_bands": {
            "inquiry": {"score": inquiry_score, "band": _inquiry_band(inquiry_score)},
            "guest_ops": "Developing",
            "maintenance": "Emerging",
            "turnover": "Emerging",
        },
        "components": {
            "readiness": scores["readiness"],
            "escalation": scores["escalation"],
            "behavior": "neutral",
        },
        "metrics": {
            "traffic_count": int(traffic_count or 0),
            "kb_entries": int(kb_entries or 0),
            "distinct_gaps": int(distinct_gaps or 0),
        },
    }


def _rollup_property_inquiry_score(property_snapshots: list[Dict[str, Any]]) -> Dict[str, Any]:
    computed_scores = [
        float(item["domain_bands"]["inquiry"]["score"])
        for item in property_snapshots
        if item.get("signal_status") == "computed"
        and item.get("domain_bands", {}).get("inquiry", {}).get("score") is not None
    ]
    included = len(computed_scores)
    excluded = len(property_snapshots) - included
    inquiry_score = round(sum(computed_scores) / included, 4) if included else None
    return {
        "inquiry_score": inquiry_score,
        "included_properties": included,
        "excluded_properties": excluded,
    }


async def _active_properties_for_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    COALESCE(to_jsonb(p)->>'id', to_jsonb(p)->>'property_id') AS property_id,
                    COALESCE(
                        to_jsonb(p)->>'property_code',
                        to_jsonb(p)->>'external_id',
                        to_jsonb(p)->>'address_street',
                        to_jsonb(p)->>'name',
                        to_jsonb(p)->>'property_name',
                        to_jsonb(p)->>'id',
                        to_jsonb(p)->>'property_id'
                    ) AS property_code
                FROM properties p
                WHERE (to_jsonb(p)->>'tenant_id') = :tid
                  AND COALESCE((to_jsonb(p)->>'is_active')::boolean, TRUE) = TRUE
                ORDER BY COALESCE(
                    to_jsonb(p)->>'property_code',
                    to_jsonb(p)->>'external_id',
                    to_jsonb(p)->>'address_street',
                    to_jsonb(p)->>'name',
                    to_jsonb(p)->>'property_name',
                    to_jsonb(p)->>'id',
                    to_jsonb(p)->>'property_id'
                )
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _kb_entry_counts_by_property(
    session: AsyncSession,
    tenant_id: str,
) -> Dict[str, int]:
    tenant_baseline = int(
        await _scalar_or(
            session,
            0,
            """
            SELECT COUNT(*)
            FROM concierge_scoped_knowledge
            WHERE tenant_id = CAST(:tid AS uuid)
              AND COALESCE(is_active, TRUE) = TRUE
              AND scope_type = 'tenant'
            """,
            {"tid": tenant_id},
        )
        or 0
    )
    rows = (
        await session.execute(
            text(
                """
                SELECT scope_target_id::text AS property_id, COUNT(*) AS n
                FROM concierge_scoped_knowledge
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND scope_type = 'property'
                GROUP BY scope_target_id
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()

    property_counts = {
        str(row["property_id"]): tenant_baseline + int(row["n"] or 0)
        for row in rows
    }
    property_counts["__tenant_baseline__"] = tenant_baseline
    return property_counts


async def _traffic_counts_by_property(
    session: AsyncSession,
    tenant_id: str,
) -> Dict[str, int]:
    from app.services.messaging_brain.knowledge.gap_recorder import resolve_property_id_from_external

    rows = (
        await session.execute(
            text(
                """
                SELECT property_external_id, COUNT(*) AS n
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND COALESCE(property_external_id, '') <> ''
                GROUP BY property_external_id
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()

    counts: dict[str, int] = defaultdict(int)
    tenant_uuid = uuid.UUID(tenant_id)
    for row in rows:
        property_external_id = str(row.get("property_external_id") or "").strip()
        if not property_external_id:
            continue
        resolved_property_id = await resolve_property_id_from_external(
            session=session,
            tenant_id=tenant_uuid,
            property_external_id=property_external_id,
        )
        if resolved_property_id:
            counts[str(resolved_property_id)] += int(row.get("n") or 0)
    return dict(counts)


async def compute_portfolio_snapshot(
    session: AsyncSession,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Compute the portfolio-level autonomy snapshot for one tenant.

    Returns a dict suitable for inserting directly into operator_autonomy_snapshots:
      {
        portfolio_score: float,          # 0..1
        domain_bands: {
          inquiry:   {score: float, band: str},
          guest_ops: str,      # band word only — not a computed number
          maintenance: str,
          turnover: str,
        },
        components: {
          readiness:  float,
          escalation: float,
          behavior:   "neutral",
        },
      }
    """
    tid = str(tenant_id)

    # -- Property count -------------------------------------------------------
    prop_count = await _scalar_or(
        session,
        0,
        "SELECT COUNT(*) FROM properties WHERE tenant_id = CAST(:tid AS uuid) AND COALESCE(is_active, TRUE) = TRUE",
        {"tid": tid},
    )

    # -- KB entries -----------------------------------------------------------
    kb_entries = 0
    try:
        kb_svc = get_dashboard_kb_service()
        kb_entries = await kb_svc.count_dashboard_entries(
            session=session,
            tenant_id=uuid.UUID(tid),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutonomyScore] KB entries fallback (tenant=%s): %s", tid, exc)
        try:
            await session.rollback()
        except Exception:
            pass

    # -- Unresolved KB gaps ---------------------------------------------------
    try:
        kb_gaps = await _count_distinct_genuine_attributed_gaps(session, tid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutonomyScore] gap-count fallback (tenant=%s): %s", tid, exc)
        try:
            await session.rollback()
        except Exception:
            pass
        kb_gaps = 0

    # -- Escalation pressure (open vs resolved last 30d) ----------------------
    esc_row = await _scalar_or(
        session,
        None,
        """
        SELECT
            COUNT(*) FILTER (WHERE e.status IN ('pending','acknowledged')) AS open,
            COUNT(*) FILTER (WHERE e.status = 'resolved'
                             AND e.resolved_at >= NOW() - INTERVAL '30 days')  AS resolved_30d
        FROM concierge_escalations e
        INNER JOIN concierge_guest_sessions s ON s.token = e.session_token
        WHERE s.tenant_id = CAST(:tid AS uuid)
        """,
        {"tid": tid},
    )
    recent_session_count = await _count_recent_guest_sessions(session, tid)

    # -- Score components -----------------------------------------------------

    # Escalation: resolved / (open + resolved_30d); higher resolved → better
    if esc_row and isinstance(esc_row, (dict,)) or (esc_row is not None and hasattr(esc_row, "_mapping")):
        # SQLAlchemy Row or mapping
        try:
            esc_mapping = esc_row._mapping if hasattr(esc_row, "_mapping") else esc_row
            esc_open = int(esc_mapping.get("open", 0) or 0)
            esc_resolved = int(esc_mapping.get("resolved_30d", 0) or 0)
        except Exception:
            esc_open, esc_resolved = 0, 0
    else:
        esc_open, esc_resolved = 0, 0

    scores = _compute_portfolio_score_from_inputs(
        property_count=int(prop_count or 0),
        kb_entries=int(kb_entries or 0),
        distinct_gaps=int(kb_gaps or 0),
        escalation_open=esc_open,
        escalation_resolved=esc_resolved,
        recent_session_count=recent_session_count,
    )

    # -- Domain bands ---------------------------------------------------------
    # Inquiry: portfolio-level proxy for v1 — uses readiness_score as a
    # directional signal. The real per-property inquiry computation is the
    # NEXT brick; this is intentionally coarse.
    inquiry_score = scores["readiness"]
    inquiry_band = _inquiry_band(inquiry_score)

    # Immature domains: band words only. Never fabricated numbers.
    domain_bands: Dict[str, Any] = {
        "inquiry": {"score": inquiry_score, "band": inquiry_band},
        "guest_ops": "Developing",
        "maintenance": "Emerging",
        "turnover": "Emerging",
    }

    components: Dict[str, Any] = {
        "readiness": scores["readiness"],
        "escalation": scores["escalation"],
        "behavior": "neutral",
    }

    return {
        "portfolio_score": scores["portfolio"],
        "domain_bands": domain_bands,
        "components": components,
    }


async def compute_autonomy_snapshot_bundle(
    session: AsyncSession,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Compute the portfolio snapshot plus the per-property Inquiry layer used by
    the autonomy capstone surfaces.
    """
    portfolio_snapshot = await compute_portfolio_snapshot(session, tenant_id)
    tid = str(tenant_id)

    active_properties = await _active_properties_for_tenant(session, tid)
    property_gap_counts = await _distinct_genuine_gap_counts_by_property(session, tid)
    property_traffic_counts = await _traffic_counts_by_property(session, tid)
    property_kb_counts = await _kb_entry_counts_by_property(session, tid)
    tenant_baseline_kb = int(property_kb_counts.get("__tenant_baseline__", 0))

    esc_row = await _scalar_or(
        session,
        None,
        """
        SELECT
            COUNT(*) FILTER (WHERE e.status IN ('pending','acknowledged')) AS open,
            COUNT(*) FILTER (WHERE e.status = 'resolved'
                             AND e.resolved_at >= NOW() - INTERVAL '30 days')  AS resolved_30d
        FROM concierge_escalations e
        INNER JOIN concierge_guest_sessions s ON s.token = e.session_token
        WHERE s.tenant_id = CAST(:tid AS uuid)
        """,
        {"tid": tid},
    )
    if esc_row and isinstance(esc_row, (dict,)) or (esc_row is not None and hasattr(esc_row, "_mapping")):
        try:
            esc_mapping = esc_row._mapping if hasattr(esc_row, "_mapping") else esc_row
            esc_open = int(esc_mapping.get("open", 0) or 0)
            esc_resolved = int(esc_mapping.get("resolved_30d", 0) or 0)
        except Exception:
            esc_open, esc_resolved = 0, 0
    else:
        esc_open, esc_resolved = 0, 0
    recent_session_count = await _count_recent_guest_sessions(session, tid)

    property_snapshots: list[Dict[str, Any]] = []
    for property_row in active_properties:
        property_id = str(property_row["property_id"])
        property_snapshots.append(
            _property_snapshot_from_inputs(
                property_id=property_id,
                property_code=property_row.get("property_code"),
                traffic_count=int(property_traffic_counts.get(property_id, 0) or 0),
                kb_entries=int(property_kb_counts.get(property_id, tenant_baseline_kb) or 0),
                distinct_gaps=int(property_gap_counts.get(property_id, 0) or 0),
                shared_escalation_open=esc_open,
                shared_escalation_resolved=esc_resolved,
                shared_recent_session_count=recent_session_count,
            )
        )

    rollup = _rollup_property_inquiry_score(property_snapshots)
    portfolio_components = dict(portfolio_snapshot.get("components") or {})
    portfolio_components["per_property_rollup"] = rollup
    portfolio_snapshot["components"] = portfolio_components

    return {
        "portfolio": portfolio_snapshot,
        "per_property": property_snapshots,
        "rollup": rollup,
    }
