"""
Conversation logging for voice and messaging sessions.
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ImportError:  # pragma: no cover - optional dependency in some envs
    psycopg2 = None
    Json = None
    RealDictCursor = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guest_conversations (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) UNIQUE NOT NULL,
    property_code VARCHAR(20),
    guest_phone VARCHAR(20),
    channel VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_seconds INT,
    turn_count INT DEFAULT 0,
    avg_response_time_ms INT,
    escalated BOOLEAN DEFAULT FALSE,
    resolved BOOLEAN DEFAULT TRUE,
    rating INT,
    conversation_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) REFERENCES guest_conversations(session_id),
    turn_id VARCHAR(50) NOT NULL,
    turn_number INT NOT NULL,
    speaker VARCHAR(20) NOT NULL,
    text TEXT NOT NULL,
    intent VARCHAR(50),
    confidence FLOAT,
    audio_duration_ms INT,
    response_time_ms INT,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_feedback (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) REFERENCES guest_conversations(session_id),
    turn_id VARCHAR(50),
    rating INT,
    feedback_type VARCHAR(20),
    feedback_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_property ON guest_conversations(property_code);
CREATE INDEX IF NOT EXISTS idx_conversations_channel ON guest_conversations(channel);
CREATE INDEX IF NOT EXISTS idx_conversations_date ON guest_conversations(started_at);
CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_intent ON conversation_turns(intent);
"""


def _connect(cursor_factory=None):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; conversation logging is unavailable")
    kwargs = {"cursor_factory": cursor_factory} if cursor_factory else {}
    return psycopg2.connect(DATABASE_URL, **kwargs)


def init_schema() -> None:
    """Initialize database schema for conversation logging."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(SCHEMA_SQL)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Conversation logging schema initialized")
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.warning("Conversation logging schema initialization skipped: %s", exc)


async def log_conversation(
    session_id: str,
    property_code: Optional[str],
    guest_phone: Optional[str],
    channel: str,
    turns: List[Any],
    started_at: datetime,
    ended_at: Optional[datetime] = None,
    escalated: bool = False,
    resolved: bool = True,
) -> None:
    """Log a complete conversation session."""
    try:
        conn = _connect(cursor_factory=RealDictCursor)
        cur = conn.cursor()

        ended_at = ended_at or datetime.now(timezone.utc)
        duration_seconds = int((ended_at - started_at).total_seconds())
        conversation_json = {
            "session_id": session_id,
            "property_code": property_code,
            "channel": channel,
            "turns": [
                {
                    "speaker": getattr(turn, "speaker", None),
                    "text": getattr(turn, "text", None),
                    "intent": getattr(turn, "intent", None),
                    "timestamp": (
                        turn.timestamp.isoformat()
                        if hasattr(getattr(turn, "timestamp", None), "isoformat")
                        else str(getattr(turn, "timestamp", ""))
                    ),
                }
                for turn in turns
            ],
        }

        cur.execute(
            """
            INSERT INTO guest_conversations (
                session_id, property_code, guest_phone, channel,
                started_at, ended_at, duration_seconds,
                turn_count, escalated, resolved, conversation_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (session_id) DO UPDATE SET
                ended_at = EXCLUDED.ended_at,
                duration_seconds = EXCLUDED.duration_seconds,
                turn_count = EXCLUDED.turn_count,
                escalated = EXCLUDED.escalated,
                resolved = EXCLUDED.resolved,
                conversation_json = EXCLUDED.conversation_json
            """,
            (
                session_id,
                property_code,
                guest_phone,
                channel,
                started_at,
                ended_at,
                duration_seconds,
                len(turns),
                escalated,
                resolved,
                Json(conversation_json),
            ),
        )

        for index, turn in enumerate(turns, start=1):
            cur.execute(
                """
                INSERT INTO conversation_turns (
                    session_id, turn_id, turn_number,
                    speaker, text, intent, confidence,
                    audio_duration_ms, response_time_ms, timestamp
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT DO NOTHING
                """,
                (
                    session_id,
                    getattr(turn, "turn_id", str(uuid4())),
                    index,
                    getattr(turn, "speaker", ""),
                    getattr(turn, "text", ""),
                    getattr(turn, "intent", None),
                    getattr(turn, "confidence", None),
                    getattr(turn, "audio_duration_ms", None),
                    getattr(turn, "response_time_ms", None),
                    getattr(turn, "timestamp", datetime.now(timezone.utc)),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.error("Failed to log conversation %s: %s", session_id, exc)


async def log_single_turn(
    session_id: str,
    property_code: Optional[str],
    guest_phone: Optional[str],
    channel: str,
    speaker: str,
    text: str,
    intent: Optional[str] = None,
    response_time_ms: Optional[int] = None,
) -> None:
    """Log a single turn for SMS or async channels."""
    try:
        conn = _connect(cursor_factory=RealDictCursor)
        cur = conn.cursor()
        now = datetime.now(timezone.utc)
        turn_id = str(uuid4())

        cur.execute(
            """
            INSERT INTO guest_conversations (
                session_id, property_code, guest_phone, channel, started_at, turn_count
            ) VALUES (
                %s, %s, %s, %s, %s, 1
            )
            ON CONFLICT (session_id) DO UPDATE SET
                turn_count = guest_conversations.turn_count + 1
            """,
            (session_id, property_code, guest_phone, channel, now),
        )

        cur.execute(
            "SELECT turn_count FROM guest_conversations WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        turn_number = row["turn_count"] if row else 1

        cur.execute(
            """
            INSERT INTO conversation_turns (
                session_id, turn_id, turn_number,
                speaker, text, intent, response_time_ms, timestamp
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (session_id, turn_id, turn_number, speaker, text, intent, response_time_ms, now),
        )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.error("Failed to log turn for %s: %s", session_id, exc)


async def log_feedback(
    session_id: str,
    turn_id: Optional[str] = None,
    rating: Optional[int] = None,
    feedback_type: Optional[str] = None,
    feedback_text: Optional[str] = None,
) -> None:
    """Log rating or feedback for a conversation."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO conversation_feedback (
                session_id, turn_id, rating, feedback_type, feedback_text
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, turn_id, rating, feedback_type, feedback_text),
        )
        if rating is not None:
            cur.execute(
                "UPDATE guest_conversations SET rating = %s WHERE session_id = %s",
                (rating, session_id),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.error("Failed to log feedback for %s: %s", session_id, exc)


def export_training_data(
    output_path: str = "training_data.jsonl",
    channel: Optional[str] = None,
    min_turns: int = 2,
    min_rating: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> int:
    """Export conversations as JSONL for model training."""
    try:
        conn = _connect(cursor_factory=RealDictCursor)
        cur = conn.cursor()

        query = """
            SELECT session_id, property_code, conversation_json, rating
            FROM guest_conversations
            WHERE turn_count >= %s
        """
        params: List[Any] = [min_turns]

        if channel:
            query += " AND channel = %s"
            params.append(channel)
        if min_rating is not None:
            query += " AND rating >= %s"
            params.append(min_rating)
        if start_date:
            query += " AND started_at >= %s"
            params.append(start_date)
        if end_date:
            query += " AND started_at <= %s"
            params.append(end_date)

        cur.execute(query, params)
        rows = cur.fetchall()

        count = 0
        with open(output_path, "w", encoding="utf-8") as handle:
            for row in rows:
                conversation = row["conversation_json"]
                if not conversation or "turns" not in conversation:
                    continue

                system_msg = (
                    "You are a helpful guest concierge for Beach Habitats vacation rentals."
                )
                if row["property_code"]:
                    system_msg += f" The guest is staying at property {row['property_code']}."

                messages = [{"role": "system", "content": system_msg}]
                for turn in conversation["turns"]:
                    role = "user" if turn["speaker"] == "guest" else "assistant"
                    messages.append({"role": role, "content": turn["text"]})

                handle.write(json.dumps({"messages": messages}) + "\n")
                count += 1

        cur.close()
        conn.close()
        logger.info("Exported %s conversations to %s", count, output_path)
        return count
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.error("Failed to export training data: %s", exc)
        return 0


def get_conversation_stats(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    property_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Get high-level analytics for conversations."""
    try:
        conn = _connect(cursor_factory=RealDictCursor)
        cur = conn.cursor()

        where_clauses: List[str] = []
        params: List[Any] = []
        if start_date:
            where_clauses.append("started_at >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("started_at <= %s")
            params.append(end_date)
        if property_code:
            where_clauses.append("property_code = %s")
            params.append(property_code)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        cur.execute(
            f"""
            SELECT
                COUNT(*) as total_conversations,
                COUNT(DISTINCT property_code) as unique_properties,
                SUM(turn_count) as total_turns,
                AVG(turn_count) as avg_turns_per_conversation,
                AVG(duration_seconds) as avg_duration_seconds,
                SUM(CASE WHEN escalated THEN 1 ELSE 0 END) as escalated_count,
                SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved_count,
                AVG(rating) as avg_rating,
                COUNT(CASE WHEN channel = 'voice' THEN 1 END) as voice_count,
                COUNT(CASE WHEN channel = 'sms' THEN 1 END) as sms_count,
                COUNT(CASE WHEN channel = 'chat' THEN 1 END) as chat_count
            FROM guest_conversations
            WHERE {where_sql}
            """,
            params,
        )
        row = cur.fetchone()

        cur.execute(
            f"""
            SELECT intent, COUNT(*) as count
            FROM conversation_turns t
            JOIN guest_conversations c ON t.session_id = c.session_id
            WHERE intent IS NOT NULL AND {where_sql}
            GROUP BY intent
            ORDER BY count DESC
            LIMIT 10
            """,
            params,
        )
        top_intents = [{"intent": r["intent"], "count": r["count"]} for r in cur.fetchall()]

        cur.close()
        conn.close()

        total_conversations = row["total_conversations"] or 0
        return {
            "total_conversations": total_conversations,
            "unique_properties": row["unique_properties"],
            "total_turns": row["total_turns"],
            "avg_turns_per_conversation": float(row["avg_turns_per_conversation"] or 0),
            "avg_duration_seconds": float(row["avg_duration_seconds"] or 0),
            "escalation_rate": (row["escalated_count"] or 0) / max(total_conversations, 1),
            "resolution_rate": (row["resolved_count"] or 0) / max(total_conversations, 1),
            "avg_rating": float(row["avg_rating"] or 0),
            "channel_breakdown": {
                "voice": row["voice_count"],
                "sms": row["sms_count"],
                "chat": row["chat_count"],
            },
            "top_intents": top_intents,
        }
    except Exception as exc:  # pragma: no cover - depends on external DB
        logger.error("Failed to get conversation stats: %s", exc)
        return {}


try:  # pragma: no cover - depends on external DB
    init_schema()
except Exception:
    pass
