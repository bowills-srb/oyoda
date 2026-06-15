#!/usr/bin/env python3
"""
verify_autonomy_cap.py — proof for #3: knowledge readiness gates autonomy.

Exercises app.services.messaging.autonomy_gate.evaluate against the local DB to
prove the new readiness cap: a property in 'auto' mode with sufficient confidence
still holds for REVIEW when its latest computed inquiry-readiness band is below
"Developing" — and auto-sends once it reaches Developing/Autonomous. Absence of
any snapshot preserves prior behavior (no cap).

Requires: local Postgres up + migrations at head + scripts/seed_local_dev.py run
(uses the seeded Sea Glass property under the default tenant).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.database import get_db_session
from app.services.messaging import autonomy_gate
from app.services.messaging.autonomy_gate import AutonomyDecision, set_property_autonomy

TENANT = UUID("00000000-0000-0000-0000-000000000001")
PROP = UUID("11111111-1111-1111-1111-111111111111")  # Sea Glass (seed_local_dev)


async def _set_band(db, band: str) -> None:
    await db.execute(
        text("""
            INSERT INTO operator_property_autonomy_snapshots
                (tenant_id, property_id, snapshot_date, inquiry_band)
            VALUES (:t, :p, CURRENT_DATE, :b)
            ON CONFLICT (tenant_id, property_id, snapshot_date)
            DO UPDATE SET inquiry_band = EXCLUDED.inquiry_band
        """),
        {"t": str(TENANT), "p": str(PROP), "b": band},
    )
    await db.commit()


async def _clear_band(db) -> None:
    await db.execute(
        text("DELETE FROM operator_property_autonomy_snapshots WHERE property_id = :p"),
        {"p": str(PROP)},
    )
    await db.commit()


async def _decide(db):
    r = await autonomy_gate.evaluate(
        db, tenant_id=TENANT, property_id=PROP, stage="all",
        confidence=0.99, policy_warnings=[],
    )
    return r.decision, r.reason


async def main() -> None:
    passed = failed = 0

    def ck(cond, label, extra=""):
        nonlocal passed, failed
        if cond:
            print(f"  PASS — {label}"); passed += 1
        else:
            print(f"  FAIL — {label}  {extra}"); failed += 1

    async with get_db_session() as db:
        if not (await db.execute(text("SELECT 1 FROM properties WHERE id = :p"), {"p": str(PROP)})).fetchone():
            print("Sea Glass property not seeded — run scripts/seed_local_dev.py first")
            sys.exit(2)

        await set_property_autonomy(
            db, tenant_id=TENANT, property_id=PROP,
            approval_mode="auto", min_confidence_for_auto=0.5, changed_by="verify",
        )

        await _clear_band(db)
        d, reason = await _decide(db)
        ck(d == AutonomyDecision.AUTO_SEND, "no snapshot → AUTO_SEND (prior behavior preserved)", f">> {d}/{reason}")

        await _set_band(db, "Emerging")
        d, reason = await _decide(db)
        ck(d == AutonomyDecision.REVIEW and "readiness" in reason.lower(),
           "Emerging band → REVIEW (capped)", f">> {d}/{reason}")

        await _set_band(db, "Insufficient Signal")
        d, _ = await _decide(db)
        ck(d == AutonomyDecision.REVIEW, "Insufficient Signal → REVIEW (capped)", f">> {d}")

        await _set_band(db, "Developing")
        d, _ = await _decide(db)
        ck(d == AutonomyDecision.AUTO_SEND, "Developing band → AUTO_SEND (allowed)", f">> {d}")

        await _set_band(db, "Autonomous")
        d, _ = await _decide(db)
        ck(d == AutonomyDecision.AUTO_SEND, "Autonomous band → AUTO_SEND (allowed)", f">> {d}")

        # cleanup
        await _clear_band(db)
        await set_property_autonomy(
            db, tenant_id=TENANT, property_id=PROP, approval_mode="required", changed_by="verify",
        )

    print(f"\n  AUTONOMY CAP (#3): {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
