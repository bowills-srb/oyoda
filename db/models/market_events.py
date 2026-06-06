"""
Market Events Model

Stores scraped local events for each operator market.
Events feed two systems:

  1. Signal pipeline  — emitted as DEMAND_PRESSURE / EVENT_IMPACT signals
                        so pricing and BD analytics see demand spikes

  2. Concierge RAG    — indexed into concierge_knowledge so guests can ask
                        "what's going on this weekend?" and get a live answer

Design notes:
  - market_id ties events to a geographic market, not an operator, so
    multiple operators in the same market share the event corpus.
  - source_url + source_id form a natural dedup key per source.
  - estimated_attendance is nullable; populated when Eventbrite / official
    sites expose it; used to weight DEMAND_PRESSURE signal confidence.
  - rag_indexed_at tracks when the event was pushed to the knowledge store
    so a background job can re-index stale or updated events.
  - Events are soft-deleted (is_active=false) rather than hard-deleted so
    historical demand-correlation analysis remains intact.
"""

from datetime import datetime, date
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Index,
    Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base


class MarketEventModel(Base):
    """
    A single local event scraped from public sources.
    Scoped to a geographic market (not an operator/tenant).
    """

    __tablename__ = "market_events"

    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # ── Market geography ─────────────────────────────────────────────────────
    market_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # e.g. "30a_fl", "destin_fl", "gulf_shores_al"

    market_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Human-readable: "30A Beaches, FL"

    # ── Event identity ────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    # music / festival / art / food / sports / family / community / holiday

    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # ["outdoor", "free", "family-friendly", "ticketed"]

    # ── Dates & times ─────────────────────────────────────────────────────────
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(20))   # "7:00 PM"
    end_time: Mapped[str | None] = mapped_column(String(20))     # "11:00 PM"
    is_multi_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(200))
    # "weekly:Saturday" / "annual"

    # ── Location ──────────────────────────────────────────────────────────────
    venue_name: Mapped[str | None] = mapped_column(String(300))
    venue_address: Mapped[str | None] = mapped_column(String(500))
    venue_lat: Mapped[float | None] = mapped_column(Float)
    venue_lng: Mapped[float | None] = mapped_column(Float)

    # ── Demand impact ─────────────────────────────────────────────────────────
    estimated_attendance: Mapped[int | None] = mapped_column(Integer)
    # Populated from Eventbrite capacity / official press releases

    demand_radius_miles: Mapped[float] = mapped_column(Float, default=15.0, nullable=False)
    # How far from the venue this event affects STR demand

    demand_impact_score: Mapped[float | None] = mapped_column(Float)
    # 0.0–1.0: computed from attendance + category + recurrence
    # Stored so the signal detector can read it directly

    guest_relevance_score: Mapped[float | None] = mapped_column(Float)
    # 0.0–1.0: how useful this is for guest-facing concierge answers

    booking_urgency_score: Mapped[float | None] = mapped_column(Float)
    # 0.0–1.0: whether a guest should take action ahead of arrival

    event_confidence_score: Mapped[float | None] = mapped_column(Float)
    # 0.0–1.0: confidence derived from source breadth + event structure

    event_class: Mapped[str | None] = mapped_column(String(50))
    # operational / demand_driver / seasonal_anchor

    actionability: Mapped[str | None] = mapped_column(String(50))
    # informational / plan_ahead / book_now

    # ── Source provenance ─────────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    # "eventbrite" / "visitflorida" / "30a_com" / "visitwaltoncounty" /
    # "facebook" / "manual"

    source_id: Mapped[str | None] = mapped_column(String(200))
    # External ID from source system (Eventbrite event_id, etc.)

    source_url: Mapped[str | None] = mapped_column(String(1000))

    source_type: Mapped[str | None] = mapped_column(String(50))
    # tourism / ticketing / venue / calendar / manual / social

    source_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_types: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    ticket_url: Mapped[str | None] = mapped_column(String(1000))
    ticket_price_range: Mapped[str | None] = mapped_column(String(100))
    # "Free" / "$15–$45" / "$95+"

    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── RAG / knowledge store ─────────────────────────────────────────────────
    rag_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Null = not yet indexed. Set by the indexing job.

    rag_knowledge_id: Mapped[str | None] = mapped_column(String(100))
    # Foreign reference to concierge_knowledge.knowledge_id

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Verified = operator or admin has confirmed accuracy

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Primary scrape dedup: one record per source+id per market
        Index("ix_market_events_source_dedup", "market_id", "source", "source_id",
              unique=True, postgresql_where="source_id IS NOT NULL"),
        # Concierge query: events by market in date range
        Index("ix_market_events_market_dates", "market_id", "start_date", "end_date"),
        # Signal query: upcoming events needing demand score
        Index("ix_market_events_upcoming", "start_date", "is_active"),
        # RAG indexing job: unindexed active events
        Index("ix_market_events_rag_pending", "rag_indexed_at", "is_active"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_rag_text(self) -> str:
        """
        Produce the text block indexed into the concierge knowledge store.
        Optimised for the concierge to answer "what's happening near me?"
        """
        lines = [f"EVENT: {self.title}"]

        date_str = self.start_date.strftime("%B %d, %Y")
        if self.is_multi_day and self.end_date != self.start_date:
            date_str += f" – {self.end_date.strftime('%B %d, %Y')}"
        if self.start_time:
            date_str += f", {self.start_time}"
        lines.append(f"When: {date_str}")

        if self.venue_name:
            loc = self.venue_name
            if self.venue_address:
                loc += f", {self.venue_address}"
            lines.append(f"Where: {loc}")

        if self.description:
            # Trim to first 300 chars for RAG chunk size
            desc = self.description[:300].rstrip()
            if len(self.description) > 300:
                desc += "…"
            lines.append(f"About: {desc}")

        if self.ticket_price_range or self.is_free:
            price = "Free" if self.is_free else self.ticket_price_range
            lines.append(f"Admission: {price}")

        if self.ticket_url:
            lines.append(f"Tickets/Info: {self.ticket_url}")

        if self.tags:
            lines.append(f"Tags: {', '.join(self.tags)}")

        return "\n".join(lines)

    def to_signal_metadata(self) -> dict:
        """Metadata dict for the DEMAND_PRESSURE signal this event generates."""
        return {
            "event_id":            str(self.event_id),
            "event_title":         self.title,
            "event_category":      self.category,
            "start_date":          self.start_date.isoformat(),
            "end_date":            self.end_date.isoformat(),
            "venue":               self.venue_name,
            "estimated_attendance":self.estimated_attendance,
            "demand_impact_score": self.demand_impact_score,
            "guest_relevance_score": self.guest_relevance_score,
            "booking_urgency_score": self.booking_urgency_score,
            "event_confidence_score": self.event_confidence_score,
            "event_class":         self.event_class,
            "actionability":       self.actionability,
            "source":              self.source,
            "source_url":          self.source_url,
            "is_recurring":        self.is_recurring,
        }


class MarketRegistryModel(Base):
    """
    Registry of all markets the platform knows about.

    Created automatically when a new operator onboards and their
    property geo is resolved.  Additional operators in the same market
    point to the same market_id — they share event data.

    The scraper scheduler uses this table to know which markets to
    run and how frequently.
    """

    __tablename__ = "market_registry"

    market_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Slug: "30a_fl", "destin_fl", "gulf_shores_al"

    market_name: Mapped[str] = mapped_column(String(200), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    # "FL", "AL", "TX", etc.

    # ── Geographic centroid & search radius ───────────────────────────────────
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_miles: Mapped[float] = mapped_column(Float, default=15.0, nullable=False)

    # ── Scrape config ─────────────────────────────────────────────────────────
    scrape_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scrape_interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scrape_status: Mapped[str | None] = mapped_column(String(50))
    # "success" / "partial" / "failed"
    last_scrape_event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Sources enabled for this market ───────────────────────────────────────
    sources_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # {
    #   "eventbrite":       { "enabled": true,  "search_radius_km": 40 },
    #   "visitflorida":     { "enabled": true },
    #   "30a_com":          { "enabled": true },
    #   "visitwaltoncounty":{ "enabled": true },
    #   "facebook":         { "enabled": false },  # requires auth
    # }

    # ── Operator linkage ──────────────────────────────────────────────────────
    operator_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # List of operator_id strings that have properties in this market.
    # Purely informational — events are shared, not per-operator.

    # ── Metadata ──────────────────────────────────────────────────────────────
    timezone: Mapped[str] = mapped_column(String(50), default="America/Chicago", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
