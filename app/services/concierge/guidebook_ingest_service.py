"""
Server-side guidebook ingestion service.

This service is the runtime replacement for the older local-script flow:
- fetch Breezeway public guidebook payloads server-side
- flatten payloads into markdown-like text
- chunk content into property-scoped knowledge documents
- replace/index chunks in knowledge_embeddings with canonical tenant metadata

The operator-facing reconcile endpoint will call this service directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_helpers import topic_default_question
from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY
from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService
from app.services.knowledge.vector_store import Document, VectorStore
from app.services.observability.slo_metrics import Counter

LOGGER = logging.getLogger(__name__)

GUIDEBOOK_SCOPED_KNOWLEDGE_WRITE_FAILURES_TOTAL = Counter(
    "guidebook_scoped_knowledge_write_failures_total",
    "Guidebook scoped-knowledge projection failures by error type.",
    ["error_type"],
)

GUIDEBOOK_API_BASE = "https://api.breezeway.io/public/guides"
DEFAULT_USER_AGENT = "Oyvoda/1.0 guidebook-ingestion"
STOP_STATUSES = {401, 403, 429}
SYSTEM_INGEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
SCOPED_KNOWLEDGE_SOURCE = "guidebook_ingest_v2"

_SECTION_RE = re.compile(r"^#{1,3}\s+.+$", re.MULTILINE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")

_SKIP_SECTIONS = {
    "reservation info",
    "getting here",
    "wifi",
    "more...",
}

_NAV_LINES = {"beach habitats 30a", "stay", "guide", "contact", "search", "about property"}

_TYPE_KEYWORDS: List[Tuple[str, str]] = [
    ("pool", "property_amenity"),
    ("bike", "property_amenity"),
    ("beach", "property_amenity"),
    ("wristband", "property_amenity"),
    ("parking", "property_info"),
    ("door", "property_info"),
    ("check in", "property_info"),
    ("check out", "property_info"),
    ("shipping", "property_info"),
    ("trash", "property_info"),
    ("recycl", "property_info"),
    ("ac unit", "property_info"),
    ("air condition", "property_info"),
    ("refrigerator", "property_info"),
    ("dishwasher", "property_info"),
    ("oven", "property_info"),
    ("coffee", "property_info"),
    ("washer", "property_info"),
    ("dryer", "property_info"),
    ("speaker", "property_info"),
    ("tv", "property_info"),
    ("television", "property_info"),
    ("cable", "property_info"),
    ("internet", "property_info"),
    ("shuttle", "local_tip"),
    ("trolley", "local_tip"),
    ("restaurant", "dining"),
    ("dining", "dining"),
    ("food", "dining"),
    ("beach chair", "activity"),
    ("beach setup", "activity"),
    ("kayak", "activity"),
    ("paddleboard", "activity"),
    ("golf cart", "activity"),
    ("rule", "property_rules"),
    ("quiet hour", "property_rules"),
    ("pet", "property_rules"),
    ("smoke", "property_rules"),
    ("noise", "property_rules"),
    ("guest", "property_rules"),
]

_TOPIC_SIGNAL_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("pet_fee", ("pet fee", "dog fee", "pet charge")),
    ("pet_policy", ("pet", "dog", "cat", "service animal")),
    ("pool_heating_cost", ("pool heating cost", "pool heat cost", "heated pool cost", "pool heating fee")),
    ("pool_heating_notice", ("pool heating notice", "pool heat notice", "pool heat in advance", "turn on pool heat", "advance notice")),
    ("pool_heating_capability", ("pool heated", "heated pool", "pool heat")),
    ("pool_access", ("pool", "swimming pool", "private pool")),
    ("hot_tub_access", ("hot tub", "jacuzzi", "spa")),
    ("beach_access", ("beach access", "walk to beach", "private beach", "public access")),
    ("beach_gear", ("beach chairs", "umbrella", "cooler", "beach gear")),
    ("golf_cart", ("golf cart",)),
    ("parking", ("parking", "park", "garage", "driveway")),
    ("sleeping_arrangement", ("bedrooms", "beds", "sleeping arrangement", "bunk room")),
    ("max_occupancy", ("how many guests", "max guests", "occupancy")),
    ("check_in_process", ("check in", "check-in", "arrival instructions", "door code")),
    ("early_check_in", ("early check in", "early arrival", "arrive early")),
    ("late_check_out", ("late check out", "late checkout", "stay later")),
    ("cleaning_fee", ("cleaning fee", "cleaning charge")),
    ("cancellation_policy", ("cancellation", "cancel", "refund")),
    ("payment_schedule", ("payment schedule", "when do i pay", "deposit due", "pay the balance")),
    ("deposit_policy", ("security deposit", "damage deposit", "hold on card", "damage waiver")),
    ("local_area", ("nearby", "neighborhood", "walk to", "restaurants nearby")),
    ("accessibility", ("accessible", "wheelchair", "stairs", "elevator")),
]


class GuidebookFetchStop(RuntimeError):
    """Raised when upstream conditions require stopping the ingest run."""


@dataclass
class GuideFetchResponse:
    status: int
    final_url: str
    content_type: str
    body: bytes

    @property
    def is_json(self) -> bool:
        return "json" in (self.content_type or "").lower()


@dataclass
class GuidebookChunk:
    property_code: str
    property_address: str
    section_title: str
    content: str
    doc_type: str
    char_count: int = 0

    def __post_init__(self) -> None:
        self.char_count = len(self.content)

    @property
    def doc_id(self) -> str:
        key = f"{self.property_code}|{self.section_title}|{self.content[:100]}"
        return "gb_" + hashlib.md5(key.encode()).hexdigest()[:14]

    def to_searchable_text(self) -> str:
        return (
            f"Property {self.property_address} ({self.property_code}). "
            f"{self.section_title}: {self.content}"
        )

    def to_metadata(
        self,
        *,
        tenant_id: UUID,
        guidebook_url: str,
    ) -> Dict[str, Any]:
        return {
            "tenant_id": str(tenant_id),
            "property_code": self.property_code,
            "property_address": self.property_address,
            "doc_type": self.doc_type,
            "section_title": self.section_title,
            "source": "breezeway_guidebook",
            "source_url": guidebook_url,
            "char_count": self.char_count,
        }


@dataclass
class ScopedKnowledgeProjection:
    topic_id: Optional[str]
    question_text: str
    answer_text: str
    tags: List[str]
    metadata: Dict[str, Any]


@dataclass
class GuidebookIngestResult:
    property_code: str
    fetched: bool
    deleted: int
    inserted: int
    updated: int
    chunk_count: int
    source_url: str
    scoped_knowledge_written: int = 0
    scoped_knowledge_failed: int = 0
    scoped_knowledge_skipped_no_property: bool = False


def _request_headers(user_agent: str) -> Dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }


def extract_guide_token(url: str) -> str:
    match = re.match(r"^https://guide\.breezeway\.io/([^/?#]+)", (url or "").strip())
    if not match:
        raise ValueError(f"Unsupported guidebook URL: {url}")
    return match.group(1)


async def fetch_guide_payload(
    guide_token: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 30.0,
) -> GuideFetchResponse:
    url = f"{GUIDEBOOK_API_BASE}/{guide_token}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=_request_headers(user_agent))
        return GuideFetchResponse(
            status=resp.status_code,
            final_url=str(resp.url),
            content_type=resp.headers.get("Content-Type", ""),
            body=resp.content,
        )


def _json_body(response: GuideFetchResponse) -> Optional[Dict[str, Any]]:
    if not response.is_json:
        return None
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def classify_known_property_skip(response: GuideFetchResponse) -> Optional[str]:
    if response.status != 422:
        return None
    body = _json_body(response) or {}
    if (
        body.get("error") == "Bad request"
        and body.get("description") == "Home Guide is not available"
    ):
        return "guide_not_configured"
    return None


def classify_stop_condition(response: GuideFetchResponse) -> Optional[str]:
    if classify_known_property_skip(response):
        return None
    if response.status in STOP_STATUSES:
        return f"HTTP {response.status} from Breezeway public guide API"
    if response.status >= 300 and response.status not in {404}:
        body = _json_body(response)
        if response.status == 422 and body:
            return (
                f"Unexpected HTTP 422 from Breezeway public guide API: "
                f"{json.dumps(body, ensure_ascii=False, sort_keys=True)}"
            )
        return f"Unexpected HTTP {response.status} from Breezeway public guide API"
    if response.status == 200 and not response.is_json:
        return f"Unexpected non-JSON content type {response.content_type or 'unknown'}"
    final_url = (response.final_url or "").lower()
    if "captcha" in final_url or "challenge" in final_url:
        return f"Suspicious redirect detected: {response.final_url}"
    body_prefix = response.body[:512].lower()
    if b"<html" in body_prefix and b"breezeway" not in body_prefix:
        return "HTML response received instead of JSON payload"
    return None


def decode_guide_payload(response: GuideFetchResponse) -> Dict[str, Any]:
    if not response.is_json:
        raise GuidebookFetchStop(
            f"Unexpected content type from Breezeway API: {response.content_type or 'unknown'}"
        )
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GuidebookFetchStop("Breezeway API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise GuidebookFetchStop("Breezeway API returned non-object JSON payload")
    return payload


def _extract_block_text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("content"), str):
            return data["content"]
        if isinstance(data.get("html"), str):
            return data["html"]
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, list):
        return "\n".join(_extract_block_text(item) for item in data if item is not None)
    return str(data)


def _html_to_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


def render_markdown_from_payload(
    payload: Dict[str, Any],
    *,
    property_code: str,
) -> str:
    lines: List[str] = [f"# Guidebook Extract: {property_code}", ""]
    for page in payload.get("pages") or []:
        page_title = str(page.get("title") or "").strip() or "Guide"
        lines.append(f"## {page_title}")
        lines.append("")
        for section in page.get("sections") or []:
            section_title = str(section.get("title") or "").strip()
            if section_title:
                lines.append(f"### {section_title}")
                lines.append("")
            for block in section.get("blocks") or []:
                raw_text = _extract_block_text(block.get("data"))
                text = _html_to_text(raw_text)
                if not text:
                    continue
                block_title = str(block.get("title") or "").strip()
                if block_title and block_title != section_title:
                    lines.append(f"#### {block_title}")
                    lines.append("")
                lines.append(text)
                lines.append("")
    return "\n".join(lines).strip() + "\n"


def _infer_doc_type(title: str, body: str) -> str:
    combined = (title + " " + body).lower()
    for keyword, doc_type in _TYPE_KEYWORDS:
        if keyword in combined:
            return doc_type
    return "property_info"


def _clean_chunk_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.strip().lower() not in _NAV_LINES:
            lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S{60,}", "", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _registry_has(topic_id: str) -> bool:
    return topic_id in TOPIC_REGISTRY


def _contains_signal(text: str, signal: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(signal.lower()) + r"(?!\w)"
    return re.search(pattern, text) is not None


def chunk_to_topic_id(chunk: GuidebookChunk) -> Optional[str]:
    combined = f"{chunk.section_title} {chunk.content[:500]}".lower()
    for topic_id, signals in _TOPIC_SIGNAL_RULES:
        if not _registry_has(topic_id):
            continue
        if any(_contains_signal(combined, signal) for signal in signals):
            return topic_id
    return None


def _freeform_question_text(section_title: str, suffix: Optional[int] = None) -> str:
    label = " ".join((section_title or "").strip().split()) or "this section"
    if suffix and suffix > 1:
        return f"What should guests know about {label.lower()}? (part {suffix})"
    return f"What should guests know about {label.lower()}?"


def build_scoped_projections(
    chunks: Iterable[GuidebookChunk],
    *,
    guidebook_url: str,
    ingest_run_id: str,
) -> List[ScopedKnowledgeProjection]:
    topic_buckets: Dict[str, Dict[str, Any]] = {}
    freeform_counts: Dict[str, int] = {}
    projections: List[ScopedKnowledgeProjection] = []

    for chunk in chunks:
        topic_id = chunk_to_topic_id(chunk)
        metadata = {
            "guidebook_url": guidebook_url,
            "section_title": chunk.section_title,
            "doc_type": chunk.doc_type,
            "char_count": chunk.char_count,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "ingest_run_id": ingest_run_id,
        }
        tags = [chunk.doc_type, "guidebook_ingest"]
        if topic_id:
            bucket = topic_buckets.setdefault(
                topic_id,
                {
                    "question_text": topic_default_question(
                        topic_id,
                        TOPIC_REGISTRY[topic_id].description,
                    ),
                    "parts": [],
                    "tags": [],
                    "metadata": metadata,
                },
            )
            bucket["parts"].append(chunk.content)
            bucket["tags"].extend(tags)
            continue

        freeform_counts[chunk.section_title] = freeform_counts.get(chunk.section_title, 0) + 1
        projections.append(
            ScopedKnowledgeProjection(
                topic_id=None,
                question_text=_freeform_question_text(
                    chunk.section_title,
                    freeform_counts[chunk.section_title],
                ),
                answer_text=chunk.content,
                tags=list(dict.fromkeys(tags)),
                metadata=metadata,
            )
        )

    for topic_id, bucket in topic_buckets.items():
        projections.append(
            ScopedKnowledgeProjection(
                topic_id=topic_id,
                question_text=str(bucket["question_text"]),
                answer_text="\n\n".join(bucket["parts"]),
                tags=list(dict.fromkeys(bucket["tags"])),
                metadata=dict(bucket["metadata"]),
            )
        )

    return projections


def parse_guidebook_markdown(
    markdown_text: str,
    *,
    property_code: str,
    property_address: str,
    min_chars: int = 60,
    max_chars: int = 1200,
) -> List[GuidebookChunk]:
    chunks: List[GuidebookChunk] = []
    sections: List[Tuple[str, str]] = []

    parts = _SECTION_RE.split(markdown_text)
    headers = _SECTION_RE.findall(markdown_text)

    if parts and parts[0].strip():
        sections.append(("Introduction", parts[0]))

    for header, body in zip(headers, parts[1:]):
        title = header.lstrip("#").strip()
        sections.append((title, body))

    for title, body in sections:
        lowered = title.lower()
        if lowered in _SKIP_SECTIONS or any(skip in lowered for skip in _SKIP_SECTIONS):
            continue

        body_clean = _clean_chunk_text(body)
        if len(body_clean) < min_chars:
            continue

        doc_type = _infer_doc_type(title, body_clean)
        if len(body_clean) <= max_chars:
            chunks.append(
                GuidebookChunk(
                    property_code=property_code,
                    property_address=property_address,
                    section_title=title,
                    content=body_clean,
                    doc_type=doc_type,
                )
            )
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\n+", body_clean) if p.strip()]
        current: List[str] = []
        current_len = 0
        for para in paragraphs:
            if current_len + len(para) > max_chars and current:
                chunks.append(
                    GuidebookChunk(
                        property_code=property_code,
                        property_address=property_address,
                        section_title=title,
                        content="\n\n".join(current),
                        doc_type=doc_type,
                    )
                )
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)
        if current:
            chunks.append(
                GuidebookChunk(
                    property_code=property_code,
                    property_address=property_address,
                    section_title=title,
                    content="\n\n".join(current),
                    doc_type=doc_type,
                )
            )

    return chunks


class GuidebookIngestService:
    """Fetch, chunk, and index property guidebooks server-side."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.vector_store = VectorStore(session)

    async def delete_property_chunks(
        self,
        *,
        tenant_id: UUID,
        property_code: str,
    ) -> int:
        result = await self.session.execute(
            text(
                """
                DELETE FROM knowledge_embeddings
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND property_code = :property_code
                """
            ),
            {"tenant_id": str(tenant_id), "property_code": property_code},
        )
        return result.rowcount or 0

    async def _resolve_property_id(
        self,
        *,
        tenant_id: UUID,
        property_code: str,
    ) -> Optional[UUID]:
        row = (
            await self.session.execute(
                text(
                    """
                    SELECT id
                    FROM properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND property_code = :code
                    LIMIT 1
                    """
                ),
                {"tid": str(tenant_id), "code": property_code},
            )
        ).fetchone()
        if not row:
            return None
        return UUID(str(row[0]))

    async def _write_chunks_to_scoped_knowledge(
        self,
        *,
        tenant_id: UUID,
        property_uuid: UUID,
        property_code: str,
        projections: List[ScopedKnowledgeProjection],
    ) -> tuple[int, int]:
        scoped_service = ScopedKnowledgeService()
        written = 0
        failed = 0

        for projection in projections:
            try:
                await scoped_service.write_scoped_knowledge(
                    session=self.session,
                    tenant_id=tenant_id,
                    user_id=SYSTEM_INGEST_USER_ID,
                    scope_type="property",
                    scope_target_id=property_uuid,
                    topic_id=projection.topic_id,
                    question_text=projection.question_text,
                    answer_text=projection.answer_text,
                    tags=projection.tags,
                    source=SCOPED_KNOWLEDGE_SOURCE,
                    metadata=projection.metadata,
                )
                written += 1
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                GUIDEBOOK_SCOPED_KNOWLEDGE_WRITE_FAILURES_TOTAL.labels(
                    error_type=error_type,
                ).inc()
                LOGGER.warning(
                    "[GuidebookIngest] scoped_knowledge_write_failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "chunk_section_title": projection.metadata.get("section_title", ""),
                        "error_type": error_type,
                    },
                    exc_info=True,
                )
                failed += 1

        return written, failed

    async def ingest_property_guidebook(
        self,
        *,
        tenant_id: UUID,
        property_code: str,
        property_address: str,
        guidebook_url: str,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> GuidebookIngestResult:
        guide_token = extract_guide_token(guidebook_url)
        try:
            response = await fetch_guide_payload(guide_token, user_agent=user_agent)
        except httpx.HTTPError as exc:
            raise GuidebookFetchStop(
                f"{property_code}: {type(exc).__name__}: {exc}"
            ) from exc

        skip_reason = classify_known_property_skip(response)
        if skip_reason:
            raise GuidebookFetchStop(f"{property_code}: {skip_reason}")

        stop_reason = classify_stop_condition(response)
        if stop_reason:
            raise GuidebookFetchStop(f"{property_code}: {stop_reason}")

        payload = decode_guide_payload(response)
        markdown_text = render_markdown_from_payload(payload, property_code=property_code)
        chunks = parse_guidebook_markdown(
            markdown_text,
            property_code=property_code,
            property_address=property_address,
        )
        ingest_run_id = str(uuid4())
        projections = build_scoped_projections(
            chunks,
            guidebook_url=guidebook_url,
            ingest_run_id=ingest_run_id,
        )
        property_uuid = await self._resolve_property_id(
            tenant_id=tenant_id,
            property_code=property_code,
        )
        scoped_knowledge_skipped_no_property = property_uuid is None
        scoped_knowledge_written = 0
        scoped_knowledge_failed = 0
        if property_uuid is None and chunks:
            LOGGER.warning(
                "[GuidebookIngest] scoped_knowledge_property_not_found",
                extra={
                    "tenant_id": str(tenant_id),
                    "property_code": property_code,
                },
            )
        elif property_uuid is not None and projections:
            scoped_knowledge_written, scoped_knowledge_failed = (
                await self._write_chunks_to_scoped_knowledge(
                    tenant_id=tenant_id,
                    property_uuid=property_uuid,
                    property_code=property_code,
                    projections=projections,
                )
            )

        deleted = await self.delete_property_chunks(
            tenant_id=tenant_id,
            property_code=property_code,
        )

        documents = [
            Document(
                doc_id=chunk.doc_id,
                content=chunk.to_searchable_text(),
                metadata=chunk.to_metadata(
                    tenant_id=tenant_id,
                    guidebook_url=guidebook_url,
                ),
            )
            for chunk in chunks
        ]
        if not documents:
            await self.session.commit()
            inserted = 0
            updated = 0
        else:
            result = await self.vector_store.add_documents(
                documents,
                batch_size=max(len(documents), 1),
            )
            inserted = int(result.get("inserted", 0))
            updated = int(result.get("updated", 0))
        return GuidebookIngestResult(
            property_code=property_code,
            fetched=True,
            deleted=deleted,
            inserted=inserted,
            updated=updated,
            chunk_count=len(chunks),
            source_url=guidebook_url,
            scoped_knowledge_written=scoped_knowledge_written,
            scoped_knowledge_failed=scoped_knowledge_failed,
            scoped_knowledge_skipped_no_property=scoped_knowledge_skipped_no_property,
        )


async def get_guidebook_ingest_service(session: AsyncSession) -> GuidebookIngestService:
    return GuidebookIngestService(session)
