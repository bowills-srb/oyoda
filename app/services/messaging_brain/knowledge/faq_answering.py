from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "can", "could", "would", "should", "what", "when", "where", "which", "who",
    "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
    "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MATCH_FLOOR = 0.45


def normalize_message_tokens(text: str) -> set[str]:
    """Tokenize and stopword-filter to mirror legacy FAQ matching."""
    if not text:
        return set()
    words = _TOKEN_RE.findall(text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def score_faq_match(
    message_text: str,
    faq: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], float]:
    """Return the best matching FAQ row and its lexical score."""
    msg_tokens = normalize_message_tokens(message_text)
    if not msg_tokens or not faq:
        return None, 0.0

    best_score = 0.0
    best_match: Optional[Dict[str, Any]] = None

    for entry in faq:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "")
        answer = str(entry.get("answer") or "")
        if not answer:
            continue

        q_tokens = normalize_message_tokens(question)
        a_tokens = normalize_message_tokens(answer)
        if not q_tokens:
            continue

        ref = q_tokens | set(list(a_tokens)[:20])
        if not ref:
            continue

        overlap_q = len(msg_tokens & q_tokens)
        overlap_any = len(msg_tokens & ref)
        score_q = overlap_q / max(len(q_tokens), 1)
        score_any = overlap_any / max(len(msg_tokens), 1)
        score = 0.7 * score_q + 0.3 * score_any

        if score > best_score and overlap_q >= 1 and score >= _MATCH_FLOOR:
            best_score = score
            best_match = {
                "question": question,
                "answer": answer,
                "source": entry.get("source"),
            }

    return best_match, best_score


def best_faq_answer(
    message_text: str,
    faq: List[Dict[str, Any]],
) -> Optional[str]:
    """Return the answer text for the best matching FAQ row, if any."""
    match, _ = score_faq_match(message_text, faq)
    return str(match["answer"]) if match else None
