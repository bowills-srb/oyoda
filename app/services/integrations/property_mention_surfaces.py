from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


SURFACE_SUBJECT = "subject"
SURFACE_LATEST_BODY = "latest_body"
SURFACE_QUOTED_CONTEXT = "quoted_context"
SURFACE_UNKNOWN = "unknown"

SURFACE_PRECEDENCE = (
    SURFACE_SUBJECT,
    SURFACE_LATEST_BODY,
    SURFACE_QUOTED_CONTEXT,
)

PROPERTY_SUBJECT_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("reservation", "request"),
    ("booking", "inquiry"),
    ("rental", "inquiry"),
    ("reservation",),
    ("inquiry",),
    ("booking",),
    ("availability",),
    ("question",),
    ("rental",),
    ("trip",),
    ("stay",),
)

PROPERTY_SUBJECT_MONTHS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

PROPERTY_SUBJECT_GENERIC_CANDIDATES = {
    "availability",
    "booking",
    "condo",
    "guest",
    "home",
    "house",
    "inquiry",
    "property",
    "question",
    "quick",
    "rental",
    "reservation",
    "stay",
    "trip",
    "vacation",
    "quick question",
}

BODY_ADDRESS_STOPWORDS = PROPERTY_SUBJECT_MONTHS | {
    "monday", "mon", "tuesday", "tue", "wednesday", "wed", "thursday", "thu",
    "friday", "fri", "saturday", "sat", "sunday", "sun",
    "on", "at", "the", "for", "and", "thank", "thanks", "best", "available",
}

BODY_ADDRESS_STREET_TYPES = {
    "street", "st", "road", "rd", "drive", "dr", "lane", "ln",
    "circle", "cir", "court", "ct", "boulevard", "blvd", "way",
    "place", "pl", "avenue", "ave", "trail", "trl", "cove", "loop",
    "walk", "terrace", "ter", "parkway", "pkwy", "highway", "hwy",
}

THREAD_SPLIT_PATTERNS = (
    re.compile(r"(?im)^\s*on .+ wrote:\s*$"),
    re.compile(r"(?im)^\s*[- ]*original message[- ]*$"),
    re.compile(r"(?im)^\s*[- ]*forwarded message[- ]*$"),
    re.compile(r"(?im)^\s*from:\s.+$"),
    re.compile(r"(?im)^\s*sent:\s.+$"),
    re.compile(r"(?im)^\s*subject:\s.+$"),
    re.compile(r"(?im)^\s*_+\s*$"),
)

_SUBJECT_PROPERTY_PATTERN = re.compile(r"(?:for|about|re:|re\s) ([A-Z][^,\n]{3,40})", re.I)
_BODY_QUOTED_PROPERTY_PATTERN = re.compile(r'"([A-Z][^"]{3,40})"')
_BODY_ADDRESS_WITH_STREET_TYPE_PATTERN = re.compile(
    r"\b("
    r"\d{1,4}\s+"
    r"(?:[NSEW]\.?\s+)?"
    r"[A-Za-z][A-Za-z'.]*"
    r"(?:\s+[A-Za-z][A-Za-z'.]*){0,2}"
    r"\s+(?:street|st|road|rd|drive|dr|lane|ln|circle|cir|court|ct|boulevard|blvd|way|place|pl|avenue|ave|trail|trl|cove|loop|walk|terrace|ter|parkway|pkwy|highway|hwy)"
    r"(?:\s+(?:Unit|Apt|Apartment|Suite|Ste|#)\s*[A-Za-z0-9-]+)?"
    r")\b",
    re.I,
)
_BODY_ADDRESS_PATTERN = re.compile(
    r"\b("
    r"\d{1,4}\s+"
    r"(?:[NSEW]\.?\s+)?"
    r"[A-Za-z][A-Za-z'.]*"
    r"(?:\s+[A-Za-z0-9#-]+){0,3}"
    r")\b",
    re.I,
)


@dataclass(frozen=True)
class SurfaceCandidate:
    surface: str
    mention: str
    confidence: float


def dissect_thread_surfaces(body: str) -> tuple[str, str]:
    text = (body or "").strip()
    if not text:
        return "", ""

    split_at = None
    for pattern in THREAD_SPLIT_PATTERNS:
        match = pattern.search(text)
        if match and (split_at is None or match.start() < split_at):
            split_at = match.start()

    latest = text[:split_at].strip() if split_at is not None else text
    older = text[split_at:].strip() if split_at is not None else ""
    return _clean_message_segment(latest)[:3000], _clean_thread_context(older)[:1500]


def extract_property_mention_candidates(
    *,
    subject: str,
    latest_body: str,
    quoted_context: str,
) -> list[SurfaceCandidate]:
    candidates: list[SurfaceCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add(surface: str, mention: str, confidence: float) -> None:
        value = (mention or "").strip()
        if not value:
            return
        key = (surface, _normalize_text(value))
        if key in seen:
            return
        seen.add(key)
        candidates.append(SurfaceCandidate(surface=surface, mention=value, confidence=confidence))

    subject_mention = _scan_subject(subject or "")
    if subject_mention:
        add(SURFACE_SUBJECT, subject_mention, 0.8)

    body_mention = _scan_body_segment((latest_body or "")[:600])
    if body_mention:
        add(SURFACE_LATEST_BODY, body_mention, 0.6)

    quoted_mention = _scan_body_segment((quoted_context or "")[:600])
    if quoted_mention:
        add(SURFACE_QUOTED_CONTEXT, quoted_mention, 0.4)

    return candidates


def select_best_candidate(candidates: list[SurfaceCandidate]) -> Optional[SurfaceCandidate]:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (c.confidence, -SURFACE_PRECEDENCE.index(c.surface)),
    )


def match_extracted_to_surfaces(
    extracted_mention: str,
    *,
    subject: str,
    latest_body: str,
    quoted_context: str,
) -> list[str]:
    needle = _normalize_text(extracted_mention)
    if not needle:
        return []

    matches: list[str] = []
    if needle in _normalize_text(subject):
        matches.append(SURFACE_SUBJECT)
    if needle in _normalize_text(latest_body):
        matches.append(SURFACE_LATEST_BODY)
    if needle in _normalize_text(quoted_context):
        matches.append(SURFACE_QUOTED_CONTEXT)
    return matches


def build_surface_audit_payload(
    *,
    parser_path: str,
    extracted_mention: str,
    subject: str,
    latest_body: str,
    quoted_context: str,
    selected_surface: str | None = None,
    selected_confidence: float | None = None,
    agreement: bool | None = None,
) -> dict[str, Any]:
    candidates = extract_property_mention_candidates(
        subject=subject,
        latest_body=latest_body,
        quoted_context=quoted_context,
    )
    matched_surfaces = match_extracted_to_surfaces(
        extracted_mention,
        subject=subject,
        latest_body=latest_body,
        quoted_context=quoted_context,
    )
    best = select_best_candidate(candidates)
    resolved_surface = selected_surface or (matched_surfaces[0] if matched_surfaces else SURFACE_UNKNOWN)
    resolved_confidence = selected_confidence if selected_confidence is not None else (best.confidence if best else None)
    available_surfaces = [
        surface
        for surface, text in (
            (SURFACE_SUBJECT, subject),
            (SURFACE_LATEST_BODY, latest_body),
            (SURFACE_QUOTED_CONTEXT, quoted_context),
        )
        if (text or "").strip()
    ]
    return {
        "type": "property_mention_surface_audit",
        "parser_path": parser_path,
        "selected_surface": resolved_surface,
        "selected_mention": (extracted_mention or "").strip() or None,
        "selected_confidence": resolved_confidence,
        "available_surfaces": available_surfaces,
        "candidate_surfaces": [candidate.surface for candidate in candidates],
        "matched_surfaces": matched_surfaces,
        "agreement": agreement,
    }


def surface_for_mention(
    extracted_mention: str,
    *,
    subject: str,
    latest_body: str,
    quoted_context: str,
) -> str:
    matches = match_extracted_to_surfaces(
        extracted_mention,
        subject=subject,
        latest_body=latest_body,
        quoted_context=quoted_context,
    )
    return matches[0] if matches else SURFACE_UNKNOWN


def _scan_subject(subject: str) -> str:
    address_candidate = _scan_body_segment(subject)
    if address_candidate:
        return address_candidate

    match = _SUBJECT_PROPERTY_PATTERN.search(subject)
    if match:
        candidate = match.group(1).strip()
        if not _is_generic(candidate):
            return candidate

    return _extract_property_from_natural_subject(subject)


def _scan_body_segment(text: str) -> str:
    match = _BODY_QUOTED_PROPERTY_PATTERN.search(text)
    if match:
        return match.group(1).strip()

    raw = _BODY_ADDRESS_WITH_STREET_TYPE_PATTERN.findall(text)
    if not raw:
        raw = _BODY_ADDRESS_PATTERN.findall(text)
    if not raw:
        return ""
    trimmed = [_trim_body_property_candidate(candidate) for candidate in raw]
    trimmed = [candidate for candidate in trimmed if candidate]
    if not trimmed:
        return ""
    street_typed = [
        candidate for candidate in trimmed
        if candidate.split() and candidate.split()[-1].casefold() in BODY_ADDRESS_STREET_TYPES
    ]
    pool = street_typed if street_typed else trimmed
    return max(pool, key=len)


def _trim_body_property_candidate(candidate: str) -> str:
    candidate = re.split(r"[.!?]\s", candidate.strip(), maxsplit=1)[0].strip()
    words = [word for word in candidate.split() if word]
    while len(words) > 1:
        tail = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", words[-1]).casefold()
        if not tail or tail in BODY_ADDRESS_STOPWORDS:
            words.pop()
            continue
        break
    return " ".join(words).strip()


def _extract_property_from_natural_subject(subject: str) -> str:
    if not subject:
        return ""

    cleaned_subject = re.sub(r"^(?:re|fwd?):\s*", "", subject, flags=re.I).strip(" -_:,")
    if not cleaned_subject:
        return ""

    original_tokens = cleaned_subject.split()
    if not original_tokens:
        return ""

    keep_count = len(original_tokens)
    lowered_tokens = [token.strip(".,!?;:()[]{}\"'").lower() for token in original_tokens]

    for suffix in PROPERTY_SUBJECT_SUFFIXES:
        if len(lowered_tokens) >= len(suffix) and tuple(lowered_tokens[-len(suffix):]) == suffix:
            keep_count -= len(suffix)
            lowered_tokens = lowered_tokens[:-len(suffix)]
            break

    while keep_count > 0:
        token = lowered_tokens[keep_count - 1]
        if token in PROPERTY_SUBJECT_MONTHS or re.fullmatch(r"\d{4}", token):
            keep_count -= 1
            continue
        break

    if keep_count <= 0:
        return ""

    candidate = " ".join(original_tokens[:keep_count]).strip(" -_:,")
    if len(candidate) < 4:
        return ""
    if candidate.lower() in PROPERTY_SUBJECT_GENERIC_CANDIDATES:
        return ""
    words = [word.strip(".,!?;:()[]{}\"'") for word in candidate.split()]
    if not words:
        return ""
    if not any(word and word[0].isupper() for word in words):
        return ""
    return candidate


def _is_generic(candidate: str) -> bool:
    lowered = candidate.lower()
    if lowered in PROPERTY_SUBJECT_GENERIC_CANDIDATES:
        return True
    return any(word in lowered for word in ("your", "the ", "our ", "a ", "quick question"))


def _clean_message_segment(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?m)^\s*>.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    blocks = []
    for block in re.split(r"\n{2,}", cleaned):
        piece = block.strip()
        if not piece:
            continue
        if re.fullmatch(r"(from|sent|to|subject):.*", piece, flags=re.I):
            continue
        blocks.append(piece)
    return "\n\n".join(blocks).strip()


def _clean_thread_context(text: str) -> str:
    context = (text or "").strip()
    if not context:
        return ""
    context = re.sub(r"(?m)^\s*> ?", "", context)
    context = re.sub(r"\n{3,}", "\n\n", context)
    return context.strip()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().casefold().split())
