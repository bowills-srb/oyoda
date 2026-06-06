"""
Operational Intelligence Engine

Joins market events × demand signals × guest sessions to produce
actionable operator insights — not raw event lists.

Design contract:
  - Raw market data NEVER surfaces directly to operators
  - Only derived, actionable insights surface: KB suggestions,
    volume alerts, contextual pre-booking guidance
  - Insights are stored in operator_insights and consumed by:
      /app/api/insights → Overview card (max 2 items)
      KB Gaps tab → correlated suggestions
      Pre-Booking view → context line
      Escalations → service risk alerts only

Platform intelligence:
  With multiple operators, the same engine produces cross-operator
  clustering: universal gap topics, event-type correlations, ADR signals.

See README.md for full architecture contract.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OperationalInsight:
    """
    A derived, actionable insight for an operator.
    Never contains raw event data — always a recommendation or alert.
    """
    insight_id: str
    tenant_id: str
    insight_type: str           # kb_suggestion | volume_alert | context_hint | service_risk
    title: str                  # Short: "Parking questions spiking"
    body: str                   # Actionable: "14 guests asked about parking near Rosemary"
    action_label: Optional[str] # "Add KB Answer" | "Review Pre-Booking" | None
    action_target: Optional[str]# "kb_gaps" | "prebooking" | "escalations" | None
    priority: str               # high | medium | low
    valid_until: date
    created_at: datetime = field(default_factory=datetime.utcnow)
    dismissed: bool = False
    source_event_ids: list = field(default_factory=list)   # market_event UUIDs
    source_gap_ids: list = field(default_factory=list)     # knowledge_gap UUIDs
    session_count: int = 0      # how many guest sessions triggered this


class OperationalInsightEngine:
    """
    Produces operator insights from the intersection of:
      - market_events (what's happening in the market)
      - signals (demand pressure)
      - knowledge_gaps (what guests couldn't get answered)
      - concierge_guest_sessions (when guests were there)

    Run daily as a background task. Results stored in operator_insights.
    Operators see max 2 active insights on Overview; rest available on demand.

    TODO: Implement _run_gap_correlation, _run_volume_alerts, _run_service_risk
    These require operator_insights table (migration 025).
    """

    async def run_for_tenant(self, tenant_id: str, market_id: str) -> list[OperationalInsight]:
        """Generate fresh insights for one operator. Called by daily background worker."""
        insights = []
        try:
            insights += await self._run_gap_event_correlation(tenant_id, market_id)
            insights += await self._run_volume_alerts(tenant_id, market_id)
            insights += await self._run_service_risk(tenant_id, market_id)
        except Exception as e:
            logger.error(f"[InsightEngine] run_for_tenant failed for {tenant_id}: {e}")
        return insights

    async def _run_gap_event_correlation(
        self, tenant_id: str, market_id: str
    ) -> list[OperationalInsight]:
        """
        Find question topics that spike during market events.

        Query: knowledge_gaps × concierge_guest_sessions × market_events
        joined by date range overlap.

        Produces: KB suggestions with event context.
        Example: "14 guests checking in during Songwriters Festival week
                  asked about parking — add a parking answer to your KB?"
        """
        from app.core.database import get_db_session
        from sqlalchemy import text
        import uuid

        insights = []
        try:
            async with get_db_session() as db:
                rows = (await db.execute(text("""
                    SELECT
                        me.title        AS event_title,
                        me.start_date,
                        me.end_date,
                        kg.question_text,
                        COUNT(DISTINCT kg.gap_id) AS guest_count,
                        ARRAY_AGG(DISTINCT kg.gap_id::text) AS gap_ids,
                        ARRAY_AGG(DISTINCT me.event_id::text) AS event_ids
                    FROM concierge_knowledge_gaps kg
                    JOIN market_events me
                        ON kg.created_at::date BETWEEN me.start_date
                                                    AND (me.end_date + INTERVAL '1 day')::date
                       AND me.market_id = :mid
                       AND me.is_active = true
                    WHERE kg.tenant_id = CAST(:tid AS uuid)
                      AND kg.resolved = false
                      AND kg.created_at > NOW() - INTERVAL '30 days'
                    GROUP BY me.title, me.start_date, me.end_date, kg.question_text
                    HAVING COUNT(DISTINCT kg.gap_id) >= 3
                    ORDER BY guest_count DESC
                    LIMIT 10
                """), {"tid": tenant_id, "mid": market_id})).fetchall()

            for row in rows:
                event_title, start, end, question, count, gap_ids, event_ids = row
                # Humanize the question topic
                topic = _extract_topic(question)
                date_str = start.strftime("%b %-d") if start else "this period"

                insights.append(OperationalInsight(
                    insight_id=str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"gap_event:{tenant_id}:{event_title}:{question}"
                    )),
                    tenant_id=tenant_id,
                    insight_type="kb_suggestion",
                    title=f"{count} guests asked about {topic} during {event_title}",
                    body=(
                        f"{count} guests checking in around {date_str} "
                        f"asked: \"{question}\". Consider adding a KB answer "
                        f"before the next similar event."
                    ),
                    action_label="Add KB Answer",
                    action_target="kb_gaps",
                    priority="high" if count >= 8 else "medium",
                    valid_until=date.today() + timedelta(days=14),
                    source_event_ids=event_ids or [],
                    source_gap_ids=gap_ids or [],
                    session_count=count,
                ))
        except Exception as e:
            logger.warning(f"[InsightEngine] gap_event_correlation failed: {e}")
        return insights

    async def _run_volume_alerts(
        self, tenant_id: str, market_id: str
    ) -> list[OperationalInsight]:
        """
        Detect upcoming high-demand periods from signals table.
        Produces: volume alerts for pre-booking and staffing.
        Example: "High-demand weekend Apr 25-27. Pre-booking drafts may increase 2x."
        """
        from app.core.database import get_db_session
        from sqlalchemy import text
        import uuid

        insights = []
        try:
            async with get_db_session() as db:
                rows = (await db.execute(text("""
                    SELECT
                        s.valid_from,
                        s.valid_until,
                        AVG(s.value) AS avg_demand,
                        COUNT(*) AS signal_count,
                        STRING_AGG(DISTINCT (s.metadata->>'explanation'), '; ') AS explanations
                    FROM signals s
                    WHERE s.geo_id = :mid
                      AND s.signal_type = 'demand_pressure'
                      AND s.valid_from BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '21 days'
                      AND s.value >= 0.60
                    GROUP BY s.valid_from, s.valid_until
                    HAVING AVG(s.value) >= 0.60
                    ORDER BY avg_demand DESC
                    LIMIT 5
                """), {"mid": market_id})).fetchall()

            for row in rows:
                valid_from, valid_until, avg_demand, sig_count, explanations = row
                date_str = valid_from.strftime("%b %-d") if valid_from else "upcoming"
                level = "High" if avg_demand >= 0.75 else "Elevated"
                multiplier = "2x" if avg_demand >= 0.75 else "1.5x"

                insights.append(OperationalInsight(
                    insight_id=str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"volume:{tenant_id}:{market_id}:{valid_from}"
                    )),
                    tenant_id=tenant_id,
                    insight_type="volume_alert",
                    title=f"{level}-demand period starting {date_str}",
                    body=(
                        f"Demand signals indicate {level.lower()} occupancy pressure "
                        f"around {date_str}. Pre-booking inquiry volume may increase "
                        f"{multiplier}. Review your auto-draft settings."
                    ),
                    action_label="Review Pre-Booking",
                    action_target="prebooking",
                    priority="high" if avg_demand >= 0.75 else "medium",
                    valid_until=valid_until if valid_until else date.today() + timedelta(days=7),
                    session_count=0,
                ))
        except Exception as e:
            logger.warning(f"[InsightEngine] volume_alerts failed: {e}")
        return insights

    async def _run_service_risk(
        self, tenant_id: str, market_id: str
    ) -> list[OperationalInsight]:
        """
        Detect service risk: high-demand periods with unresolved KB gaps
        in high-frequency question topics.
        Produces: escalation-level alerts when gaps + demand overlap.
        """
        # Placeholder — fires when gap_event_correlation finds high-count
        # gaps AND a volume_alert exists for the same window.
        # Full implementation in next iteration.
        return []


def _extract_topic(question: str) -> str:
    """Distill a raw guest question into a short topic label."""
    q = question.lower()
    if any(w in q for w in ["park", "parking", "car"]):
        return "parking"
    if any(w in q for w in ["shuttle", "transport", "uber", "lyft", "ride"]):
        return "transportation"
    if any(w in q for w in ["beach", "access", "public beach"]):
        return "beach access"
    if any(w in q for w in ["restaurant", "food", "eat", "dinner", "lunch"]):
        return "dining"
    if any(w in q for w in ["chair", "umbrella", "towel", "gear"]):
        return "beach gear"
    if any(w in q for w in ["wifi", "internet", "password"]):
        return "WiFi"
    if any(w in q for w in ["check", "early", "late", "checkout", "checkin"]):
        return "check-in/out"
    if any(w in q for w in ["pet", "dog", "animal"]):
        return "pet policy"
    # Fallback: first 4 words
    words = question.split()[:4]
    return " ".join(words).rstrip("?").lower()


# Singleton
_engine: Optional[OperationalInsightEngine] = None


def get_insight_engine() -> OperationalInsightEngine:
    global _engine
    if _engine is None:
        _engine = OperationalInsightEngine()
    return _engine
