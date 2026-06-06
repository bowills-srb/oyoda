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

group_session.py — Multi-guest session support for Oyvoda concierge.

Allows multiple guests in the same booking party to each have their own
1-to-1 conversation with Coral, all backed by the same session context.

Architecture:
  - One parent session (concierge_guest_sessions) per booking — unchanged
  - N group members (guest_group_members) — one row per additional guest
  - Each member has their own phone number and a display name
  - Inbound message lookup checks group_members AFTER checking lead guest phone
  - All members share the same property context, phase, and KB

Flow:
  1. Operator creates session for lead guest (Sarah, +1-555-0100)
  2. Welcome SMS includes: "Share Oyvo with your group → oyvoda.com/join/abc123"
  3. Sarah's husband Mike taps the link, enters his name and phone
  4. Mike gets a welcome SMS: "Hi Mike! I'm Oyvo, Sarah's co-host..."
  5. Both Sarah and Mike can text Oyvo independently
  6. Operator dashboard shows both conversations under one booking

Rate limiting:
  - Max 8 members per session (reasonable vacation party limit)
  - Max 150 messages per member per stay
  - Join link expires at checkout + 24h

Join token:
  - Format: oj_{16_random_chars}
  - Stored in concierge_guest_sessions.group_join_token
  - Join URL: https://oyvoda.com/c/join/{join_token}
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_GROUP_MEMBERS = 8          # Max additional guests per session
MAX_MESSAGES_PER_MEMBER = 150  # Rate limit per member per stay
JOIN_TOKEN_PREFIX = "oj_"


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GroupMember:
    """An additional guest registered against a session."""
    member_id: UUID
    session_id: UUID
    phone_number: str           # E.164 format
    display_name: str           # First name only, shown in dashboard
    role: str                   # "guest" (all additional guests are "guest")
    message_count: int
    joined_at: datetime
    last_message_at: Optional[datetime]
    is_active: bool


@dataclass
class JoinResult:
    """Result of a guest joining a session via the share link."""
    success: bool
    member: Optional[GroupMember] = None
    session_token: Optional[str] = None
    property_name: Optional[str] = None
    concierge_name: Optional[str] = None
    concierge_emoji: Optional[str] = None
    operator_name: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    welcome_message: Optional[str] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# DB Migration SQL
# ─────────────────────────────────────────────────────────────────────────────

MIGRATION_SQL = """
-- Group members table
CREATE TABLE IF NOT EXISTS guest_group_members (
    member_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES concierge_guest_sessions(session_id)
                            ON DELETE CASCADE,
    tenant_id           UUID NOT NULL,
    phone_number        TEXT NOT NULL,
    display_name        TEXT NOT NULL DEFAULT 'Guest',
    role                TEXT NOT NULL DEFAULT 'guest',
    message_count       INTEGER NOT NULL DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_group_member_session_phone
    ON guest_group_members (session_id, phone_number);

CREATE INDEX IF NOT EXISTS idx_group_member_phone
    ON guest_group_members (phone_number)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_group_member_session
    ON guest_group_members (session_id);

-- Add group_join_token column to sessions table if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'concierge_guest_sessions'
          AND column_name = 'group_join_token'
    ) THEN
        ALTER TABLE concierge_guest_sessions
            ADD COLUMN group_join_token TEXT UNIQUE;
    END IF;
END $$;

-- Add group_member_count column for quick lookups
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'concierge_guest_sessions'
          AND column_name = 'group_member_count'
    ) THEN
        ALTER TABLE concierge_guest_sessions
            ADD COLUMN group_member_count INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sessions_join_token
    ON concierge_guest_sessions (group_join_token)
    WHERE group_join_token IS NOT NULL;
"""


async def run_group_migration(db: AsyncSession) -> None:
    """Create guest_group_members table and add join token columns. Idempotent."""
    try:
        await db.execute(text(MIGRATION_SQL))
        await db.commit()
        logger.info("[GroupSession] Migration complete")
    except Exception as e:
        logger.warning("[GroupSession] Migration failed (non-fatal): %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# GroupSessionService
# ─────────────────────────────────────────────────────────────────────────────

class GroupSessionService:
    """
    Manages multi-guest session membership.

    Usage:
        svc = GroupSessionService()

        # Generate a join token for a session (called when session is created)
        token = await svc.get_or_create_join_token(db, session_id)
        join_url = f"https://oyvoda.com/c/join/{token}"

        # Guest taps the link and submits their name+phone
        result = await svc.join_session(db, join_token, "Mike", "+15550200")

        # Inbound message lookup — check lead guest AND group members
        session_row = await svc.lookup_session_for_phone(db, "+15550200")

        # Check if this phone is a group member (not lead)
        member = await svc.get_member_by_phone(db, session_id, "+15550200")

        # Increment message count + rate limit check
        ok = await svc.check_and_increment_message_count(db, session_id, "+15550200")
    """

    # ── Join token management ─────────────────────────────────────────────

    @staticmethod
    def _generate_join_token() -> str:
        return JOIN_TOKEN_PREFIX + secrets.token_urlsafe(16)

    async def get_or_create_join_token(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> str:
        """
        Get the existing join token for a session, or create one if none exists.
        The token never changes for a session — stable shareable URL.
        """
        result = await db.execute(
            text("""
                SELECT group_join_token FROM concierge_guest_sessions
                WHERE session_id = :sid
            """),
            {"sid": str(session_id)},
        )
        row = result.fetchone()
        if row and row[0]:
            return row[0]

        token = self._generate_join_token()
        await db.execute(
            text("""
                UPDATE concierge_guest_sessions
                SET group_join_token = :token, updated_at = NOW()
                WHERE session_id = :sid
            """),
            {"token": token, "sid": str(session_id)},
        )
        await db.commit()
        return token

    async def get_session_by_join_token(
        self,
        db: AsyncSession,
        join_token: str,
    ):
        """Look up a session row by its join token."""
        result = await db.execute(
            text("""
                SELECT * FROM concierge_guest_sessions
                WHERE group_join_token = :token
                  AND status NOT IN ('expired', 'closed')
                  AND check_out >= CURRENT_DATE - INTERVAL '1 day'
                LIMIT 1
            """),
            {"token": join_token},
        )
        return result.fetchone()

    # ── Member management ─────────────────────────────────────────────────

    async def join_session(
        self,
        db: AsyncSession,
        join_token: str,
        display_name: str,
        phone_number: str,
    ) -> JoinResult:
        """
        Register a new group member against a session via join token.
        Returns a JoinResult with the welcome message and session context.
        """
        phone_number = _normalize_phone(phone_number)
        display_name = display_name.strip()[:50] or "Guest"

        # Look up session
        session_row = await self.get_session_by_join_token(db, join_token)
        if not session_row:
            return JoinResult(
                success=False,
                error="This link has expired or is no longer valid.",
            )

        session_id = session_row.session_id
        tenant_id = session_row.tenant_id

        # Check if this phone is the lead guest already
        lead_phone = _normalize_phone(session_row.guest_phone or "")
        if lead_phone and lead_phone == phone_number:
            return JoinResult(
                success=False,
                error="You're already connected as the primary guest.",
            )

        # Check member count
        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM guest_group_members
                WHERE session_id = :sid AND is_active = TRUE
            """),
            {"sid": str(session_id)},
        )
        count = count_result.scalar() or 0
        if count >= MAX_GROUP_MEMBERS:
            return JoinResult(
                success=False,
                error=f"This booking has reached the maximum of {MAX_GROUP_MEMBERS} guests.",
            )

        # Check if this phone already joined
        existing = await self.get_member_by_phone(db, session_id, phone_number)
        if existing and existing.is_active:
            # Already joined — just return their context
            return await self._build_join_result(
                db, session_row, existing, already_joined=True
            )

        # Insert new member
        member_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO guest_group_members
                    (member_id, session_id, tenant_id, phone_number,
                     display_name, role, message_count, is_active, joined_at)
                VALUES
                    (:mid, :sid, :tid, :phone, :name, 'guest', 0, TRUE, NOW())
                ON CONFLICT (session_id, phone_number) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    is_active = TRUE,
                    updated_at = NOW()
            """),
            {
                "mid": str(member_id),
                "sid": str(session_id),
                "tid": str(tenant_id),
                "phone": phone_number,
                "name": display_name,
            },
        )

        # Increment group_member_count on parent session
        await db.execute(
            text("""
                UPDATE concierge_guest_sessions
                SET group_member_count = COALESCE(group_member_count, 0) + 1,
                    updated_at = NOW()
                WHERE session_id = :sid
            """),
            {"sid": str(session_id)},
        )
        await db.commit()

        member = GroupMember(
            member_id=member_id,
            session_id=session_id,
            phone_number=phone_number,
            display_name=display_name,
            role="guest",
            message_count=0,
            joined_at=datetime.utcnow(),
            last_message_at=None,
            is_active=True,
        )

        result = await self._build_join_result(db, session_row, member)

        # Send welcome SMS to the new member
        if result.success and result.welcome_message:
            try:
                from app.services.messaging.channel_router import (
                    get_channel_router, ChannelMessage
                )
                router = get_channel_router()
                await router.send(
                    to=phone_number,
                    message=ChannelMessage(body=result.welcome_message),
                )
                logger.info(
                    "[GroupSession] Welcome sent to %s for session %s",
                    phone_number, session_id,
                )
            except Exception as e:
                logger.warning("[GroupSession] Welcome SMS failed (non-fatal): %s", e)

        return result

    async def _build_join_result(
        self,
        db: AsyncSession,
        session_row,
        member: GroupMember,
        already_joined: bool = False,
    ) -> JoinResult:
        """Build a JoinResult from session row and member."""
        property_name = session_row.property_name or "the property"
        concierge_name = getattr(session_row, "concierge_name", None) or "Oyvo"
        concierge_emoji = getattr(session_row, "concierge_emoji", None) or "🐚"
        operator_name = getattr(session_row, "operator_name", None) or "your host"
        check_in = session_row.check_in
        check_out = session_row.check_out

        # Build welcome message
        lead_name = (session_row.guest_name or "").split()[0]
        if already_joined:
            welcome = (
                f"Welcome back, {member.display_name}! {concierge_emoji}\n\n"
                f"You're already connected. Just text this number with any questions "
                f"about {property_name}."
            )
        else:
            welcome = (
                f"Hi {member.display_name}! {concierge_emoji} I'm {concierge_name}, "
                f"{lead_name}'s co-host at {property_name}.\n\n"
                f"Text me anything — WiFi, local spots, checkout, you name it. "
                f"I'm here 24/7."
            )

        return JoinResult(
            success=True,
            member=member,
            session_token=session_row.token,
            property_name=property_name,
            concierge_name=concierge_name,
            concierge_emoji=concierge_emoji,
            operator_name=operator_name,
            check_in=check_in,
            check_out=check_out,
            welcome_message=welcome,
        )

    async def get_member_by_phone(
        self,
        db: AsyncSession,
        session_id: UUID,
        phone_number: str,
    ) -> Optional[GroupMember]:
        """Get a group member by session + phone."""
        result = await db.execute(
            text("""
                SELECT member_id, session_id, phone_number, display_name,
                       role, message_count, joined_at, last_message_at, is_active
                FROM guest_group_members
                WHERE session_id = :sid AND phone_number = :phone
                LIMIT 1
            """),
            {"sid": str(session_id), "phone": phone_number},
        )
        row = result.fetchone()
        if not row:
            return None
        return GroupMember(
            member_id=row.member_id,
            session_id=row.session_id,
            phone_number=row.phone_number,
            display_name=row.display_name,
            role=row.role,
            message_count=row.message_count,
            joined_at=row.joined_at,
            last_message_at=row.last_message_at,
            is_active=row.is_active,
        )

    async def get_session_for_phone(
        self,
        db: AsyncSession,
        phone_number: str,
    ):
        """
        Find the active session for any phone — lead guest OR group member.
        This replaces _lookup_session_by_phone in sms.py.

        Returns the concierge_guest_sessions row, plus a `_member_name` attribute
        injected for personalized responses to group members.
        """
        phone_number = _normalize_phone(phone_number)

        # ── 1. Check lead guest phone first (fast, indexed) ───────────────
        result = await db.execute(
            text("""
                SELECT *, NULL::text AS _member_name
                FROM concierge_guest_sessions
                WHERE guest_phone = :phone
                  AND status NOT IN ('expired', 'closed')
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"phone": phone_number},
        )
        row = result.fetchone()
        if row:
            return row

        # ── 2. Check group members ─────────────────────────────────────────
        result = await db.execute(
            text("""
                SELECT s.*, m.display_name AS _member_name
                FROM guest_group_members m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE m.phone_number = :phone
                  AND m.is_active = TRUE
                  AND s.status NOT IN ('expired', 'closed')
                  AND s.check_out >= CURRENT_DATE - INTERVAL '1 day'
                ORDER BY m.joined_at DESC
                LIMIT 1
            """),
            {"phone": phone_number},
        )
        return result.fetchone()

    # ── Rate limiting ─────────────────────────────────────────────────────

    async def check_and_increment_message_count(
        self,
        db: AsyncSession,
        session_id: UUID,
        phone_number: str,
    ) -> bool:
        """
        Check rate limit and increment message count for a group member.
        Returns True if within limit, False if rate limited.
        Does nothing (returns True) if phone is the lead guest.
        """
        result = await db.execute(
            text("""
                SELECT message_count FROM guest_group_members
                WHERE session_id = :sid AND phone_number = :phone AND is_active = TRUE
            """),
            {"sid": str(session_id), "phone": phone_number},
        )
        row = result.fetchone()
        if not row:
            return True  # Lead guest — not tracked here

        if row.message_count >= MAX_MESSAGES_PER_MEMBER:
            logger.warning(
                "[GroupSession] Rate limit reached for %s in session %s",
                phone_number, session_id,
            )
            return False

        await db.execute(
            text("""
                UPDATE guest_group_members
                SET message_count = message_count + 1,
                    last_message_at = NOW(),
                    updated_at = NOW()
                WHERE session_id = :sid AND phone_number = :phone
            """),
            {"sid": str(session_id), "phone": phone_number},
        )
        await db.commit()
        return True

    # ── Dashboard helpers ─────────────────────────────────────────────────

    async def get_group_members(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> List[GroupMember]:
        """Get all active group members for a session."""
        result = await db.execute(
            text("""
                SELECT member_id, session_id, phone_number, display_name,
                       role, message_count, joined_at, last_message_at, is_active
                FROM guest_group_members
                WHERE session_id = :sid AND is_active = TRUE
                ORDER BY joined_at ASC
            """),
            {"sid": str(session_id)},
        )
        return [
            GroupMember(
                member_id=r.member_id,
                session_id=r.session_id,
                phone_number=r.phone_number,
                display_name=r.display_name,
                role=r.role,
                message_count=r.message_count,
                joined_at=r.joined_at,
                last_message_at=r.last_message_at,
                is_active=r.is_active,
            )
            for r in result.fetchall()
        ]

    async def remove_member(
        self,
        db: AsyncSession,
        session_id: UUID,
        phone_number: str,
    ) -> bool:
        """Soft-delete a group member (operator action)."""
        result = await db.execute(
            text("""
                UPDATE guest_group_members
                SET is_active = FALSE, updated_at = NOW()
                WHERE session_id = :sid AND phone_number = :phone
            """),
            {"sid": str(session_id), "phone": phone_number},
        )
        await db.execute(
            text("""
                UPDATE concierge_guest_sessions
                SET group_member_count = GREATEST(0, group_member_count - 1),
                    updated_at = NOW()
                WHERE session_id = :sid
            """),
            {"sid": str(session_id)},
        )
        await db.commit()
        return result.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Helper to build the group share URL for a session
# ─────────────────────────────────────────────────────────────────────────────

def build_group_join_url(join_token: str, base_url: str = "https://oyvoda.com") -> str:
    return f"{base_url}/c/join/{join_token}"


def build_group_invite_text(
    join_url: str,
    concierge_name: str = "Oyvo",
    concierge_emoji: str = "🐚",
) -> str:
    """
    The share line appended to the lead guest's welcome message.
    Kept short — one line, one tap.
    """
    return f"Share {concierge_emoji} {concierge_name} with your group: {join_url}"


def _normalize_phone(phone: str) -> str:
    phone = (
        phone.replace(" ", "")
             .replace("-", "")
             .replace("(", "")
             .replace(")", "")
             .replace(".", "")
    )
    if not phone.startswith("+"):
        if phone.startswith("1") and len(phone) == 11:
            phone = "+" + phone
        elif len(phone) == 10:
            phone = "+1" + phone
        else:
            phone = "+" + phone
    return phone


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_group_service: Optional[GroupSessionService] = None


def get_group_session_service() -> GroupSessionService:
    global _group_service
    if _group_service is None:
        _group_service = GroupSessionService()
    return _group_service
