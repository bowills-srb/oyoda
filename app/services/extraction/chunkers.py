from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html import unescape
import re
from typing import Any, Optional, Protocol

from bs4 import BeautifulSoup, Tag

from app.services.extraction.canonical_block_service import CanonicalBlock

HTML_PARSER = "html.parser"


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def estimate_tokens(text: str) -> int:
    normalized = _normalize_text(text)
    if not normalized:
        return 0
    return max(1, (len(normalized) + 3) // 4)


def _extract_block_html(block: CanonicalBlock) -> str:
    data = block.block_content.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str):
            return content
    return ""


def _plain_text_from_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, HTML_PARSER)
    return _normalize_text(unescape(soup.get_text(" ", strip=True)))


def _make_chunk_id(source_block_hash: str, order_within_block: int, content_html: str) -> str:
    digest = hashlib.sha256(
        f"{source_block_hash}:{order_within_block}:{content_html}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def _serialize_node(node: Tag) -> str:
    return str(node)


def _iter_top_level_tags(html: str) -> list[Tag]:
    soup = BeautifulSoup(f"<div>{html}</div>", HTML_PARSER)
    container = soup.find("div")
    if container is None:
        return []
    return [child for child in container.children if isinstance(child, Tag)]


def _heading_text(tag: Tag) -> str:
    return _normalize_text(tag.get_text(" ", strip=True))


def _strong_text(tag: Tag) -> str:
    strong_tags = tag.find_all("strong")
    if strong_tags:
        parts = [strong.get_text(" ", strip=True) for strong in strong_tags]
    else:
        bold_tags = tag.find_all("b")
        parts = [bold.get_text(" ", strip=True) for bold in bold_tags]
    return _normalize_text(" ".join(parts))


def _is_heading_like(tag: Tag) -> bool:
    if tag.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return True
    if tag.name not in {"p", "div"}:
        return False
    text_value = _heading_text(tag)
    if not text_value or len(text_value) > 140:
        return False
    strong_value = _strong_text(tag)
    if not strong_value:
        return False
    return text_value == strong_value


def _is_question_like(tag: Tag) -> bool:
    if not _is_heading_like(tag):
        return False
    text_value = _heading_text(tag)
    return text_value.endswith("?") or text_value.lower().startswith(("what ", "how ", "can ", "do ", "does ", "is ", "are "))


def _first_words(text: str, limit: int = 8) -> Optional[str]:
    words = _normalize_text(text).split()
    if not words:
        return None
    short = " ".join(words[:limit])
    if len(words) > limit:
        return f"{short}..."
    return short


@dataclass(frozen=True)
class ChunkedContent:
    chunk_id: str
    source_block_hash: str
    section_title: Optional[str]
    order_within_block: int
    content_html: str
    content_text: str
    metadata: dict[str, Any]


class Chunker(Protocol):
    render_type: str

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        ...


def _chunk_from_parts(
    canonical_block: CanonicalBlock,
    *,
    order_within_block: int,
    content_html: str,
    section_title: Optional[str],
    metadata: Optional[dict[str, Any]] = None,
    allow_empty_text: bool = False,
) -> Optional[ChunkedContent]:
    normalized_html = content_html.strip()
    content_text = _plain_text_from_html(normalized_html)
    if not normalized_html or (not content_text and not allow_empty_text):
        return None
    return ChunkedContent(
        chunk_id=_make_chunk_id(canonical_block.block_hash, order_within_block, normalized_html),
        source_block_hash=canonical_block.block_hash,
        section_title=_normalize_text(section_title) if section_title else None,
        order_within_block=order_within_block,
        content_html=normalized_html,
        content_text=content_text,
        metadata=metadata or {},
    )


class FAQChunker:
    render_type = "guide_content.faqs"

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        html = _extract_block_html(canonical_block)
        tags = _iter_top_level_tags(html)
        chunks: list[ChunkedContent] = []
        current_question: Optional[str] = None
        current_nodes: list[str] = []
        current_metadata: dict[str, Any] = {}
        order = 0

        def flush(*, orphan_question: bool = False) -> None:
            nonlocal order, current_question, current_nodes, current_metadata
            if current_question is None:
                current_nodes = []
                current_metadata = {}
                return
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=order,
                section_title=current_question,
                content_html="".join(current_nodes) if current_nodes else "<p></p>",
                metadata={
                    **current_metadata,
                    "original_question_text": current_question,
                    "orphan_question": orphan_question or not current_nodes,
                },
                allow_empty_text=orphan_question or not current_nodes,
            )
            if chunk:
                chunks.append(chunk)
                order += 1
            current_question = None
            current_nodes = []
            current_metadata = {}

        for tag in tags:
            if _is_question_like(tag):
                if current_question is not None:
                    flush()
                current_question = _heading_text(tag)
                current_metadata = {"question_tag": tag.name}
                continue
            if current_question is not None:
                current_nodes.append(_serialize_node(tag))

        if current_question is not None:
            flush(orphan_question=not current_nodes)

        return chunks


class HeadingChunker:
    def __init__(self, render_type: str) -> None:
        self.render_type = render_type

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        html = _extract_block_html(canonical_block)
        tags = _iter_top_level_tags(html)
        chunks: list[ChunkedContent] = []
        current_title: Optional[str] = None
        current_nodes: list[str] = []
        current_meta: dict[str, Any] = {}
        order = 0

        def flush() -> None:
            nonlocal order, current_title, current_nodes, current_meta
            if not current_nodes:
                current_title = None
                current_meta = {}
                return
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=order,
                section_title=current_title,
                content_html="".join(current_nodes),
                metadata=current_meta,
            )
            if chunk:
                chunks.append(chunk)
                order += 1
            current_title = None
            current_nodes = []
            current_meta = {}

        for tag in tags:
            if _is_heading_like(tag):
                flush()
                current_title = _heading_text(tag)
                current_meta = {
                    "heading_tag": tag.name,
                    "heading_like": True,
                }
                continue
            current_nodes.append(_serialize_node(tag))

        flush()
        if chunks:
            return chunks

        fallback = _chunk_from_parts(
            canonical_block,
            order_within_block=0,
            section_title=None,
            content_html=html,
            metadata={"fallback": "single_chunk"},
        )
        return [fallback] if fallback else []


class ListChunker:
    def __init__(self, render_type: str) -> None:
        self.render_type = render_type

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        html = _extract_block_html(canonical_block)
        soup = BeautifulSoup(f"<div>{html}</div>", HTML_PARSER)
        container = soup.find("div")
        if container is None:
            return []

        chunks: list[ChunkedContent] = []
        order = 0
        top_lists = [tag for tag in container.find_all(["ul", "ol"], recursive=False)]
        if top_lists:
            for list_tag in top_lists:
                for li in list_tag.find_all("li", recursive=False):
                    chunk = _chunk_from_parts(
                        canonical_block,
                        order_within_block=order,
                        section_title=_first_words(li.get_text(" ", strip=True)),
                        content_html=_serialize_node(li),
                        metadata={"list_type": list_tag.name},
                    )
                    if chunk:
                        chunks.append(chunk)
                        order += 1
            return chunks

        for tag in container.find_all("p", recursive=False):
            text_value = _heading_text(tag)
            if not text_value:
                continue
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=order,
                section_title=_first_words(text_value),
                content_html=_serialize_node(tag),
                metadata={"fallback": "paragraph"},
            )
            if chunk:
                chunks.append(chunk)
                order += 1
        return chunks


class TravelTipsChunker:
    render_type = "guide_content.travel_tips"

    def __init__(self) -> None:
        self._heading = HeadingChunker(self.render_type)

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        html = _extract_block_html(canonical_block)
        tags = _iter_top_level_tags(html)
        if any(_is_heading_like(tag) for tag in tags):
            return self._heading.chunk(canonical_block)

        chunks: list[ChunkedContent] = []
        order = 0
        for tag in tags:
            text_value = _heading_text(tag)
            if not text_value:
                continue
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=order,
                section_title=_first_words(text_value),
                content_html=_serialize_node(tag),
                metadata={"fallback": "paragraph"},
            )
            if chunk:
                chunks.append(chunk)
                order += 1
        return chunks


class TrashInfoChunker:
    render_type = "home.trash_info_note"

    def chunk(self, canonical_block: CanonicalBlock) -> list[ChunkedContent]:
        html = _extract_block_html(canonical_block)
        text_value = _plain_text_from_html(html)
        if estimate_tokens(text_value) <= 500:
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=0,
                section_title=None,
                content_html=html,
                metadata={"strategy": "single_chunk"},
            )
            return [chunk] if chunk else []

        chunks: list[ChunkedContent] = []
        for order, tag in enumerate(_iter_top_level_tags(html)):
            chunk = _chunk_from_parts(
                canonical_block,
                order_within_block=order,
                section_title=_first_words(_heading_text(tag)),
                content_html=_serialize_node(tag),
                metadata={"strategy": "paragraph_fallback"},
            )
            if chunk:
                chunks.append(chunk)
        return chunks


EXTRACTOR_RENDER_TYPES = {
    "home.about_note": HeadingChunker("home.about_note"),
    "guide_content.faqs": FAQChunker(),
    "guide_content.rules": ListChunker("guide_content.rules"),
    "guide_content.departure_instructions": ListChunker("guide_content.departure_instructions"),
    "guide_content.travel_tips": TravelTipsChunker(),
    "home.trash_info_note": TrashInfoChunker(),
}


def get_chunker(render_type: str) -> Optional[Chunker]:
    return EXTRACTOR_RENDER_TYPES.get(str(render_type or ""))


def chunk_canonical_block(canonical_block: CanonicalBlock) -> list[ChunkedContent]:
    chunker = get_chunker(canonical_block.render_type)
    if chunker is None:
        return []
    return chunker.chunk(canonical_block)
