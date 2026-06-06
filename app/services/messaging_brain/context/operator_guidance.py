from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.session_safety import safe_rollback


async def load_operator_guidance(company_id: UUID, db: Any) -> str:
    """Fetch free-form House Rules / AI Guidance for one operator.

    Preserves the legacy fail-open contract: missing table/row or query
    errors return an empty string so draft generation can continue.
    """
    try:
        from sqlalchemy import text as _text

        row = await db.execute(
            _text(
                """
                SELECT guidance_text FROM operator_ai_guidance
                WHERE company_id = CAST(:cid AS uuid)
                LIMIT 1
                """
            ),
            {"cid": str(company_id)},
        )
        record = row.fetchone()
        if record and record[0]:
            return str(record[0]).strip()
    except Exception:
        await safe_rollback(db)
    return ""
