"""
conversation_history_service.py — DB-backed conversation history for drafting.

Solves the multi-turn drafting problem: when we draft a reply to an inbound
message, we need to know what the guest and the operator have already said in
this conversation. Without this, the AI treats every email as a fresh inquiry
and either repeats itself or contradicts what we've already promised.

This service loads the prior turns from `pre_booking_inquiries` joined on
`guest_thread_id`, formats them as a clean transcript, and returns a string
ready to be injected into the drafting prompt.

This is the foundation for both:
  - the legacy drafting path (`pre_booking_auto_send.generate_inquiry_draft`)
  - the messaging brain composer (`llm_composer_agent._build_user_message`)

Both paths receive the same DB-loaded history, ensuring consistent multi-turn
behavior regardless of which composer ran for any given message.

DESIGN NOTES
============

What counts as a turn the guest actually saw:

  - Inbound (`message_text` from any row): always counts. The guest sent
    every inbound message regardless of whether we replied, drafted, or
    rejected.

  - Outbound (`final_reply` from `status='replied'` rows): counts ONLY when
    status='replied'. That's the only status that proves we successfully
    delivered the text to the guest. Drafts in `pending_review`, `hold`, or
    `rejected` are NOT included — the guest never saw them and putting them
    in the history would make the AI think it had said things it never sent.

History size cap:

  Last 10 turns. We pull the NEWEST up-to-20 rows from the DB (each row
  produces 1-2 turns), then sort ascending and slice the chronological turn
  list to the last 10. Most threads in practice are short enough that we
  get the whole thing; the cap protects prompt size against pathological
  50-turn threads.

  Critical: the SQL fetches in DESCENDING order. The earliest implementation
  used ASC + LIMIT and dropped the most recent rows on long threads — the
  exact failure mode this feature exists to fix. We always fetch newest-first
  in SQL and reverse to chronological order in memory before formatting, so
  long threads get fresh context, never stale context.

Sort order (output):

  Chronological ascending — oldest first, newest last. This matches how a
  human reads a transcript and how the AI expects conversation history to
  flow into "and now reply to the latest message."

Read-only by design:

  This service does NOT write. It does not call ensure_inquiry_thread, does
  not insert rows, does not update `guest_thread_id` columns. Thread identity
  is established in the existing `_save_inquiry` path via `ensure_inquiry_thread`,
  which is idempotent. The resolver here just looks up an existing identity
  for read.

Empty-result handling:

  If no rows are found (first message of a new thread, or the thread doesn't
  exist yet), we return an empty string. Callers should treat empty history
  as "no prior context, draft as if this is the first message." This keeps
  the contract simple and avoids leaking implementation details upward.

Failure handling:

  All DB exceptions are caught, the session is rolled back, and the function
  returns an empty string. Drafting is more important than history; a
  history-load failure should never crash a draft. The error is logged at
  WARNING so it surfaces in observability without being load-bearing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Maximum rows fetched from DB per call. Each row produces 1-2 turns
# (inbound always, outbound if status='replied'). 20 rows ≈ up to 40 turns,
# which is more than enough headroom; the slice-to-last-10 below is the
# real cap.
#
# IMPORTANT: rows are fetched newest-first (DESC) in SQL so long threads
# get the most recent context, not the start of the conversation. The
# rows are then reversed in memory before formatting. See `load_prior_turns`.
_MAX_ROWS_FETCHED = 20

# Maximum turns rendered into the prompt history block. Last N wins —
# we want recency, not the start of the thread.
_MAX_TURNS_RENDERED = 10

# Per-turn character cap. Long emails get truncated with an ellipsis. Keeps
# the prompt size bounded even if the conversation contains a wall-of-text
# message. The truncation is informational only (the full text remains in
# the DB row).
_MAX_CHARS_PER_TURN = 600


@dataclass(frozen=True)
class ConversationTurn:
    """One turn in a conversation transcript.

    role:
        "guest" — guest sent this
        "operator" — we sent this (delivered, status='replied')
    content:
        The text the guest sent or the text the guest received.
    occurred_at:
        Timestamp for chronological ordering. May be None if the source
        row didn't carry a timestamp; treated as datetime.min during sort.
    """

    role: str
    content: str
    occurred_at: Optional[datetime]


async def load_prior_turns(
    db: AsyncSession,
    *,
    guest_thread_id: str,
    exclude_message_id: str = "",
) -> List[ConversationTurn]:
    """Load prior conversation turns for a guest_thread_id.

    Returns the last N turns in chronological order (oldest first, newest
    last). Returns an empty list if the thread has no prior rows or if the
    DB read fails.

    On long threads (more rows than `_MAX_ROWS_FETCHED`), this function
    returns turns drawn from the NEWEST rows in the thread, not the oldest.
    The SQL query orders by `created_at DESC` and applies LIMIT, then the
    rows are reversed in memory to produce chronological ordering. This
    matters because the multi-turn feature exists specifically to give the
    drafter recent context (latest operator commitments, latest guest asks);
    fetching ASC + LIMIT would drop exactly the rows we need and feed stale
    context into the prompt.

    Parameters
    ----------
    db:
        Active async SQLAlchemy session.
    guest_thread_id:
        UUID string identifying the thread. If empty or None, returns [].
    exclude_message_id:
        Optional Gmail message_id to exclude. If we're loading history for
        a brand-new inbound that has just been parsed but not yet persisted,
        callers can pass the current message_id here as a defensive guard
        (in practice, the new row hasn't been written yet, so this is
        rarely needed; included for callers that want belt-and-suspenders).
    """
    if not guest_thread_id:
        return []

    try:
        # Fetch newest-first to ensure long threads get recent context.
        # We reverse to chronological order in Python before formatting.
        # See the docstring above and the module-level note on
        # _MAX_ROWS_FETCHED for why this ordering is load-bearing.
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        message_text,
                        final_reply,
                        status,
                        message_id,
                        received_at,
                        replied_at,
                        created_at
                    FROM pre_booking_inquiries
                    WHERE guest_thread_id = CAST(:gtid AS uuid)
                      AND (:exclude_id = '' OR message_id IS NULL OR message_id <> :exclude_id)
                    ORDER BY created_at DESC
                    LIMIT :max_rows
                    """
                ),
                {
                    "gtid": guest_thread_id,
                    "exclude_id": exclude_message_id or "",
                    "max_rows": _MAX_ROWS_FETCHED,
                },
            )
        ).mappings().all()
    except Exception as exc:
        # Best-effort: roll back to clear any aborted-transaction state and
        # return empty history. Drafting must continue.
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning(
            "[ConversationHistory] load_prior_turns failed for guest_thread_id=%s: %s",
            guest_thread_id,
            exc,
        )
        return []

    # Rows arrived newest-first. Reverse to chronological (oldest-first)
    # before turning each row into 1-2 turns. We could equivalently sort
    # the resulting `turns` list by `occurred_at`, and we still do that
    # below as a safety net (a row's `received_at` and `replied_at` may
    # not be in the same order as `created_at` on retried/edited paths),
    # but reversing here keeps row-order intuition correct for readers.
    rows = list(reversed(rows))

    turns: List[ConversationTurn] = []
    for row in rows:
        # Inbound: every row's message_text is something the guest sent.
        message_text = (row.get("message_text") or "").strip()
        if message_text:
            turns.append(
                ConversationTurn(
                    role="guest",
                    content=_truncate(message_text),
                    occurred_at=row.get("received_at") or row.get("created_at"),
                )
            )

        # Outbound: include only when status='replied' AND final_reply is non-empty.
        # That's the only state that proves the guest actually received the text.
        if row.get("status") == "replied":
            final_reply = (row.get("final_reply") or "").strip()
            if final_reply:
                turns.append(
                    ConversationTurn(
                        role="operator",
                        content=_truncate(final_reply),
                        occurred_at=row.get("replied_at") or row.get("created_at"),
                    )
                )

    # Sort chronologically by per-turn timestamp. None timestamps sort to
    # the bottom (treat as very old) — they shouldn't happen in practice
    # but we don't want a NULL to break the sort. This is a safety net on
    # top of the row-level reverse above.
    turns.sort(key=lambda t: t.occurred_at or datetime.min)

    # Cap at the last N turns. Recency wins. By this point `turns` is
    # already chronological (oldest first), and we already fetched
    # newest-row-first in SQL, so slicing to the tail correctly preserves
    # the most recent operator commitments and guest asks.
    if len(turns) > _MAX_TURNS_RENDERED:
        turns = turns[-_MAX_TURNS_RENDERED:]

    return turns


def format_turns_for_prompt(turns: List[ConversationTurn]) -> str:
    """Render a list of turns as a transcript ready for an LLM prompt.

    Returns an empty string if turns is empty. Otherwise returns a
    plain-text transcript like:

        [Guest, 2026-05-04 10:32]:
        Hi, do you allow pets?

        [Operator, 2026-05-04 11:15]:
        Hi Sarah! We do welcome small dogs with a $75 pet fee.

        [Guest, 2026-05-05 09:02]:
        Great. What's the check-in time?

    Format choices:
      - Bracketed role + timestamp on its own line, then the content
        below. Mirrors a clear chat transcript.
      - Role names are capitalized so the LLM treats them as labels, not
        prose.
      - Timestamps are ISO-truncated to minute precision; we don't need
        seconds and they make the prompt noisier.
      - Blank line between turns for readability.
      - No leading or trailing whitespace.
    """
    if not turns:
        return ""

    lines: List[str] = []
    for turn in turns:
        role_label = "Guest" if turn.role == "guest" else "Operator"
        timestamp = (
            turn.occurred_at.strftime("%Y-%m-%d %H:%M")
            if turn.occurred_at
            else "unknown time"
        )
        lines.append(f"[{role_label}, {timestamp}]:")
        lines.append(turn.content)
        lines.append("")  # blank line separator

    # Drop the trailing blank line.
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


async def load_history_for_prompt(
    db: AsyncSession,
    *,
    guest_thread_id: str,
    exclude_message_id: str = "",
) -> str:
    """Convenience: load prior turns and format them as a single string.

    This is the canonical entry point for callers that just want the
    formatted history block to inject into a prompt. Returns an empty
    string if there's no prior history or if anything goes wrong.
    """
    turns = await load_prior_turns(
        db,
        guest_thread_id=guest_thread_id,
        exclude_message_id=exclude_message_id,
    )
    return format_turns_for_prompt(turns)


def _truncate(content: str) -> str:
    """Cap a single turn's text at the per-turn limit with an ellipsis."""
    text = (content or "").strip()
    if len(text) <= _MAX_CHARS_PER_TURN:
        return text
    return text[: _MAX_CHARS_PER_TURN - 3].rstrip() + "..."


__all__ = [
    "ConversationTurn",
    "load_prior_turns",
    "format_turns_for_prompt",
    "load_history_for_prompt",
]
