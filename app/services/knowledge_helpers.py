from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


def normalize_message_tokens(text: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in stopwords}


def normalize_question_key(text: str) -> str:
    return " ".join(sorted(normalize_message_tokens(text)))


def topic_default_question(topic_id: str, description: str) -> str:
    topic_words = topic_id.replace("_", " ")
    if "cost" in topic_id or "fee" in topic_id:
        return f"What should guests know about {topic_words}?"
    if "policy" in topic_id:
        return f"What is the {topic_words.replace('_', ' ')}?"
    if "check" in topic_id or "access" in topic_id or "process" in topic_id:
        return f"What should guests know about {topic_words}?"
    return f"What should guests know about {description.rstrip('.')}?"


async def flush_quietly(session: AsyncSession) -> None:
    flush = getattr(session, "flush", None)
    if flush is None:
        return
    maybe = flush()
    if hasattr(maybe, "__await__"):
        await maybe


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
