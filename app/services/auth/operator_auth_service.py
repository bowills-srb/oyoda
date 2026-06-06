"""
operator_auth_service.py — DB-backed operator authentication.

Replaces Railway env var operator accounts with a proper multi-tenant
auth system stored entirely in Supabase. No Railway changes needed
for new operators, team members, or Gmail credentials.

Tables created:
  operator_accounts      one row per operator company (the tenant)
  operator_team_members  employees within an operator account
  operator_gmail_creds   Gmail OAuth credentials per operator
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────────────────────────────────────

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS operator_accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,   -- login email (owner's personal)
    messaging_email     TEXT,                   -- inbox where guest msgs arrive (may differ)
    email_provider      TEXT DEFAULT 'google',  -- google | microsoft | other
    password_hash       TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    owner_name          TEXT NOT NULL,
    phone               TEXT,
    pms                 TEXT DEFAULT 'escapia',
    property_count      INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    plan                TEXT NOT NULL DEFAULT 'growth',
    onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotently add columns if table already exists from earlier migration
DO $ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='operator_accounts' AND column_name='messaging_email') THEN
        ALTER TABLE operator_accounts ADD COLUMN messaging_email TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='operator_accounts' AND column_name='email_provider') THEN
        ALTER TABLE operator_accounts ADD COLUMN email_provider TEXT DEFAULT 'google';
    END IF;
END $;
CREATE INDEX IF NOT EXISTS idx_op_accounts_email  ON operator_accounts (email);
CREATE INDEX IF NOT EXISTS idx_op_accounts_tenant ON operator_accounts (tenant_id);

CREATE TABLE IF NOT EXISTS operator_team_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    email           TEXT NOT NULL,
    password_hash   TEXT,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'staff',
    invite_token    TEXT UNIQUE,
    invite_expires  TIMESTAMPTZ,
    activated       BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (operator_id, email)
);
CREATE INDEX IF NOT EXISTS idx_team_email  ON operator_team_members (email);
CREATE INDEX IF NOT EXISTS idx_team_op     ON operator_team_members (operator_id);
CREATE INDEX IF NOT EXISTS idx_team_invite ON operator_team_members (invite_token)
    WHERE invite_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS operator_gmail_creds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL UNIQUE REFERENCES operator_accounts(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    watched_email   TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    email_provider  TEXT DEFAULT 'google',   -- google | microsoft
    inbox_go_live_at TIMESTAMPTZ,
    last_polled_at  TIMESTAMPTZ,
    last_poll_success BOOLEAN,
    last_poll_summary TEXT,
    last_poll_error TEXT,
    last_messages_found INTEGER,
    last_new_pending_inquiries INTEGER,
    last_query_mode TEXT,
    gmail_watch_history_id TEXT,
    gmail_watch_expires_at TIMESTAMPTZ,
    last_push_received_at TIMESTAMPTZ,
    last_push_history_id TEXT,
    last_push_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='operator_gmail_creds' AND column_name='email_provider') THEN
        ALTER TABLE operator_gmail_creds ADD COLUMN email_provider TEXT DEFAULT 'google';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='operator_gmail_creds' AND column_name='last_polled_at') THEN
        ALTER TABLE operator_gmail_creds
            ADD COLUMN last_polled_at TIMESTAMPTZ,
            ADD COLUMN last_poll_success BOOLEAN,
            ADD COLUMN last_poll_summary TEXT,
            ADD COLUMN last_poll_error TEXT,
            ADD COLUMN last_messages_found INTEGER,
            ADD COLUMN last_new_pending_inquiries INTEGER,
            ADD COLUMN last_query_mode TEXT,
            ADD COLUMN inbox_go_live_at TIMESTAMPTZ,
            ADD COLUMN gmail_watch_history_id TEXT,
            ADD COLUMN gmail_watch_expires_at TIMESTAMPTZ,
            ADD COLUMN last_push_received_at TIMESTAMPTZ,
            ADD COLUMN last_push_history_id TEXT,
            ADD COLUMN last_push_error TEXT;
    END IF;
END $;
CREATE INDEX IF NOT EXISTS idx_gmail_creds_op ON operator_gmail_creds (operator_id);
"""


async def run_auth_migration(db: AsyncSession) -> None:
    """
    Previously ran CREATE TABLE IF NOT EXISTS at startup.
    Tables are now managed by Alembic migration 019_operator_auth.py.
    This function is kept as a no-op for backwards compatibility.
    """
    logger.info("[OperatorAuth] Tables managed by Alembic — skipping runtime migration")


# ─────────────────────────────────────────────────────────────────────────────
# Auth result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AuthUser:
    id: str
    tenant_id: str
    operator_id: str
    email: str
    name: str
    company_name: str
    role: str               # owner | manager | staff | super_admin
    is_owner: bool
    plan: str
    property_count: int
    onboarding_complete: bool
    source: str             # "db" | "env"


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class OperatorAuthService:

    # ── Signup ────────────────────────────────────────────────────────────────

    async def create_account(
        self, db: AsyncSession,
        email: str, password: str,
        company_name: str, owner_name: str,
        phone: Optional[str] = None,
        messaging_email: Optional[str] = None,
        email_provider: str = "google",
        pms: str = "escapia",
        property_count: int = 0,
        plan: str = "growth",
    ) -> Dict[str, Any]:
        """
        Create a new operator account.
        messaging_email is the inbox where guest messages arrive — may differ
        from the login email (e.g. lanier@ vs info@beachhabitats30a.com).
        Raises ValueError if email already registered.
        """
        from app.core.security_layer import hash_password

        email = email.lower().strip()
        # messaging_email defaults to login email if not provided
        msg_email = (messaging_email or email).lower().strip()

        existing = await db.execute(
            text("SELECT id FROM operator_accounts WHERE email=:e"), {"e": email}
        )
        if existing.fetchone():
            raise ValueError(f"An account with {email} already exists.")

        aid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        await db.execute(
            text("""
                INSERT INTO operator_accounts
                    (id, tenant_id, email, messaging_email, email_provider,
                     password_hash, company_name, owner_name, phone,
                     pms, property_count, plan, status, onboarding_complete)
                VALUES (:id,:tid,:email,:msg_email,:ep,:pw,:co,:own,:ph,
                        :pms,:props,:plan,'active',FALSE)
            """),
            {"id": aid, "tid": tid, "email": email,
             "msg_email": msg_email, "ep": email_provider,
             "pw": hash_password(password),
             "co": company_name.strip(), "own": owner_name.strip(),
             "ph": phone, "pms": pms, "props": property_count, "plan": plan},
        )
        await db.commit()
        logger.info("[OperatorAuth] Account created: %s (%s) inbox=%s",
                    email, company_name, msg_email)
        return {"id": aid, "tenant_id": tid, "email": email,
                "messaging_email": msg_email, "email_provider": email_provider,
                "company_name": company_name, "owner_name": owner_name,
                "plan": plan, "onboarding_complete": False}

    # ── Login ─────────────────────────────────────────────────────────────────

    async def authenticate(
        self, db: AsyncSession, email: str, password: str
    ) -> Optional[AuthUser]:
        """
        Authenticate operator owner or team member.
        Returns AuthUser on success, None on failure.
        """
        from app.core.security_layer import verify_password
        import secrets as _s

        email = email.lower().strip()

        def _check(stored: str, plain: str) -> bool:
            if not stored:
                return False
            if stored.startswith("$2b$") or stored.startswith("$2a$"):
                return verify_password(plain, stored)
            return _s.compare_digest(plain, stored)

        # Owner account
        r = await db.execute(
            text("""
                SELECT id, tenant_id, password_hash, company_name, owner_name,
                       plan, property_count, onboarding_complete, status
                FROM operator_accounts WHERE email=:e LIMIT 1
            """), {"e": email}
        )
        row = r.fetchone()
        if row:
            if row.status == "suspended":
                return None
            if not _check(row.password_hash, password):
                return None
            return AuthUser(
                id=str(row.id), tenant_id=str(row.tenant_id),
                operator_id=str(row.id), email=email,
                name=row.owner_name or email.split("@")[0],
                company_name=row.company_name, role="owner",
                is_owner=True, plan=row.plan or "growth",
                property_count=row.property_count or 0,
                onboarding_complete=bool(row.onboarding_complete),
                source="db",
            )

        # Team member
        tm = await db.execute(
            text("""
                SELECT tm.id, tm.operator_id, tm.tenant_id, tm.password_hash,
                       tm.name, tm.role,
                       oa.company_name, oa.plan, oa.property_count, oa.onboarding_complete
                FROM operator_team_members tm
                JOIN operator_accounts oa ON oa.id = tm.operator_id
                WHERE tm.email=:e AND tm.activated=TRUE LIMIT 1
            """), {"e": email}
        )
        tm_row = tm.fetchone()
        if tm_row:
            if not _check(tm_row.password_hash, password):
                return None
            await db.execute(
                text("UPDATE operator_team_members SET last_login_at=NOW() WHERE id=:id"),
                {"id": str(tm_row.id)}
            )
            await db.commit()
            return AuthUser(
                id=str(tm_row.id), tenant_id=str(tm_row.tenant_id),
                operator_id=str(tm_row.operator_id), email=email,
                name=tm_row.name, company_name=tm_row.company_name,
                role=tm_row.role or "staff", is_owner=False,
                plan=tm_row.plan or "growth",
                property_count=tm_row.property_count or 0,
                onboarding_complete=bool(tm_row.onboarding_complete),
                source="db",
            )

        return None

    # ── Team management ───────────────────────────────────────────────────────

    async def invite_team_member(
        self, db: AsyncSession,
        operator_id: str, tenant_id: str,
        email: str, name: str, role: str = "staff",
    ) -> Dict[str, Any]:
        email = email.lower().strip()
        ex = await db.execute(
            text("SELECT id, activated FROM operator_team_members WHERE operator_id=:op AND email=:e"),
            {"op": operator_id, "e": email}
        )
        ex_row = ex.fetchone()
        if ex_row and ex_row.activated:
            raise ValueError(f"{email} is already an active team member.")

        tok = secrets.token_urlsafe(32)
        exp = datetime.utcnow() + timedelta(days=7)

        if ex_row:
            await db.execute(
                text("UPDATE operator_team_members SET invite_token=:t,invite_expires=:e,name=:n,role=:r WHERE id=:id"),
                {"t": tok, "e": exp, "n": name, "r": role, "id": str(ex_row.id)}
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO operator_team_members
                        (id,operator_id,tenant_id,email,name,role,invite_token,invite_expires,activated)
                    VALUES (:id,:op,:tid,:email,:name,:role,:tok,:exp,FALSE)
                """),
                {"id": str(uuid.uuid4()), "op": operator_id, "tid": tenant_id,
                 "email": email, "name": name, "role": role, "tok": tok, "exp": exp}
            )
        await db.commit()

        base = os.getenv("BASE_URL", "https://oyvoda.com")
        return {"invite_token": tok,
                "invite_url": f"{base}/app/accept-invite/{tok}",
                "expires_at": exp.isoformat(),
                "email": email, "name": name, "role": role}

    async def accept_invite(
        self, db: AsyncSession, invite_token: str, password: str
    ) -> Optional[Dict[str, Any]]:
        from app.core.security_layer import hash_password
        r = await db.execute(
            text("""
                SELECT id, email, name, role, operator_id, tenant_id,
                       invite_expires, activated
                FROM operator_team_members WHERE invite_token=:t LIMIT 1
            """), {"t": invite_token}
        )
        row = r.fetchone()
        if not row or row.activated or datetime.utcnow() > row.invite_expires:
            return None
        await db.execute(
            text("""
                UPDATE operator_team_members
                SET password_hash=:pw, activated=TRUE,
                    invite_token=NULL, invite_expires=NULL, updated_at=NOW()
                WHERE id=:id
            """), {"pw": hash_password(password), "id": str(row.id)}
        )
        await db.commit()
        return {"id": str(row.id), "email": row.email, "name": row.name,
                "role": row.role, "operator_id": str(row.operator_id),
                "tenant_id": str(row.tenant_id)}

    async def list_team_members(self, db, operator_id) -> List[Dict]:
        r = await db.execute(
            text("""
                SELECT id, email, name, role, activated, invite_expires,
                       last_login_at, created_at
                FROM operator_team_members WHERE operator_id=:op ORDER BY created_at
            """), {"op": operator_id}
        )
        return [{"id": str(x.id), "email": x.email, "name": x.name, "role": x.role,
                 "activated": x.activated, "invite_pending": not x.activated,
                 "invite_expires": x.invite_expires.isoformat() if x.invite_expires else None,
                 "last_login_at": x.last_login_at.isoformat() if x.last_login_at else None,
                 "joined_at": x.created_at.isoformat()} for x in r.fetchall()]

    async def remove_team_member(self, db, operator_id, member_id):
        r = await db.execute(
            text("DELETE FROM operator_team_members WHERE id=:m AND operator_id=:op"),
            {"m": member_id, "op": operator_id}
        )
        await db.commit()
        return r.rowcount > 0

    async def update_member_role(self, db, operator_id, member_id, new_role):
        if new_role not in ("manager", "staff"):
            raise ValueError(f"Invalid role: {new_role}")
        r = await db.execute(
            text("UPDATE operator_team_members SET role=:r,updated_at=NOW() WHERE id=:m AND operator_id=:op"),
            {"r": new_role, "m": member_id, "op": operator_id}
        )
        await db.commit()
        return r.rowcount > 0

    # ── Gmail credentials ─────────────────────────────────────────────────────

    async def store_gmail_creds(self, db, operator_id, tenant_id, watched_email, refresh_token):
        await db.execute(
            text(
                """
                ALTER TABLE operator_gmail_creds
                    ADD COLUMN IF NOT EXISTS inbox_go_live_at TIMESTAMPTZ
                """
            )
        )
        await db.execute(
            text("""
                INSERT INTO operator_gmail_creds (
                    operator_id,
                    tenant_id,
                    watched_email,
                    refresh_token,
                    inbox_go_live_at
                )
                VALUES (:op,:tid,:email,:tok,NOW())
                ON CONFLICT (operator_id) DO UPDATE SET
                    watched_email=EXCLUDED.watched_email,
                    refresh_token=EXCLUDED.refresh_token,
                    inbox_go_live_at=NOW(),
                    updated_at=NOW()
            """),
            {"op": operator_id, "tid": tenant_id, "email": watched_email, "tok": refresh_token}
        )
        await db.commit()
        return True

    async def get_all_gmail_creds(self, db) -> List[Dict]:
        r = await db.execute(text("""
            SELECT gc.operator_id, gc.tenant_id, gc.watched_email, gc.refresh_token,
                   oa.company_name, oa.messaging_email, oa.email_provider
            FROM operator_gmail_creds gc
            JOIN operator_accounts oa ON oa.id=gc.operator_id
            WHERE oa.status='active'
        """))
        return [
            {
                "operator_id":   str(x.operator_id),
                "tenant_id":     str(x.tenant_id),
                "watched_email": x.watched_email or getattr(x, "messaging_email", "") or "",
                "refresh_token": x.refresh_token,
                "company_name":  x.company_name,
                "email_provider": getattr(x, "email_provider", "google") or "google",
            }
            for x in r.fetchall()
        ]

    # ── Admin helpers ─────────────────────────────────────────────────────────

    async def list_all_operators(self, db) -> List[Dict]:
        r = await db.execute(text("""
            SELECT id, tenant_id, email, company_name, owner_name, plan,
                   property_count, status, onboarding_complete, created_at
            FROM operator_accounts ORDER BY created_at DESC
        """))
        return [{"id": str(x.id), "tenant_id": str(x.tenant_id), "email": x.email,
                 "company_name": x.company_name, "owner_name": x.owner_name,
                 "plan": x.plan, "property_count": x.property_count,
                 "status": x.status, "onboarding_complete": x.onboarding_complete,
                 "created_at": x.created_at.isoformat()} for x in r.fetchall()]

    async def mark_onboarding_complete(self, db, operator_id):
        await db.execute(
            text("UPDATE operator_accounts SET onboarding_complete=TRUE,updated_at=NOW() WHERE id=:id"),
            {"id": operator_id}
        )
        await db.commit()


# Singleton
_auth_service: Optional[OperatorAuthService] = None

def get_operator_auth_service() -> OperatorAuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = OperatorAuthService()
    return _auth_service
