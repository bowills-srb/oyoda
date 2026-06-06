from __future__ import annotations

from uuid import UUID

from app.services.extraction.canonical_block_service import CanonicalBlock
from app.services.extraction.chunkers import (
    FAQChunker,
    HeadingChunker,
    ListChunker,
    TrashInfoChunker,
    TravelTipsChunker,
    chunk_canonical_block,
    estimate_tokens,
)


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")


def _block(render_type: str, data) -> CanonicalBlock:
    return CanonicalBlock(
        block_hash="abc123hash",
        render_type=render_type,
        tenant_id=TENANT_ID,
        canonical_source_property_id=PROPERTY_ID,
        canonical_page_id=3362,
        applicable_property_ids=[PROPERTY_ID],
        scope_type="property",
        duplicate_group_metadata=None,
        duplicate_count=1,
        block_content={
            "id": 1,
            "render_type": render_type,
            "title": "Sample",
            "data": data,
        },
    )


def test_faq_chunker_splits_question_answer_pairs():
    html = {
        "content": (
            '<p><strong>What is check-in?</strong></p>'
            '<p>Check-in is at 4PM.</p>'
            '<p><strong>Can we check out late?</strong></p>'
            '<ul><li>Sometimes, based on schedule.</li></ul>'
            '<p><strong>Do you allow pets?</strong></p>'
        )
    }
    chunks = FAQChunker().chunk(_block("guide_content.faqs", html))

    assert len(chunks) == 3
    assert chunks[0].section_title == "What is check-in?"
    assert chunks[0].content_text == "Check-in is at 4PM."
    assert chunks[1].section_title == "Can we check out late?"
    assert "Sometimes, based on schedule." in chunks[1].content_text
    assert chunks[2].metadata["orphan_question"] is True


def test_heading_chunker_respects_heading_boundaries():
    html = (
        "<p><strong>Parking:</strong></p><p>Two vehicles fit in driveway.</p>"
        "<p><strong>Door locks:</strong></p><ul><li>Lift handle to lock.</li></ul>"
    )
    chunks = HeadingChunker("home.about_note").chunk(_block("home.about_note", html))

    assert len(chunks) == 2
    assert chunks[0].section_title == "Parking:"
    assert chunks[0].content_text == "Two vehicles fit in driveway."
    assert chunks[1].section_title == "Door locks:"
    assert "Lift handle to lock." in chunks[1].content_text


def test_heading_chunker_falls_back_to_single_chunk_without_headings():
    html = "<p>This property has a great location.</p><p>Enjoy your stay.</p>"
    chunks = HeadingChunker("home.about_note").chunk(_block("home.about_note", html))

    assert len(chunks) == 1
    assert chunks[0].section_title is None
    assert "This property has a great location." in chunks[0].content_text


def test_list_chunker_splits_list_items():
    html = {"content": "<ul><li>No smoking</li><li>Quiet hours start at 10PM</li></ul>"}
    chunks = ListChunker("guide_content.rules").chunk(_block("guide_content.rules", html))

    assert len(chunks) == 2
    assert chunks[0].content_text == "No smoking"
    assert chunks[1].content_text == "Quiet hours start at 10PM"


def test_list_chunker_falls_back_to_paragraphs():
    html = {"content": "<p>Place towels on the floor.</p><p>Start dishwasher.</p>"}
    chunks = ListChunker("guide_content.departure_instructions").chunk(
        _block("guide_content.departure_instructions", html)
    )

    assert len(chunks) == 2
    assert chunks[0].metadata["fallback"] == "paragraph"
    assert chunks[1].content_text == "Start dishwasher."


def test_travel_tips_chunker_uses_paragraph_units_without_headings():
    html = {
        "content": "<p>Bring sunscreen.</p><p>Bring beach towels.</p><p>Bring condiments.</p>"
    }
    chunks = TravelTipsChunker().chunk(_block("guide_content.travel_tips", html))

    assert len(chunks) == 3
    assert chunks[0].content_text == "Bring sunscreen."
    assert chunks[1].content_text == "Bring beach towels."


def test_trash_info_chunker_stays_single_for_short_content():
    html = "<p>Trash comes every day when the flag is raised.</p>"
    chunks = TrashInfoChunker().chunk(_block("home.trash_info_note", html))

    assert len(chunks) == 1
    assert chunks[0].metadata["strategy"] == "single_chunk"


def test_trash_info_chunker_splits_long_content():
    html = "".join(f"<p>Paragraph {i} {'x' * 800}</p>" for i in range(3))
    chunks = TrashInfoChunker().chunk(_block("home.trash_info_note", html))

    assert len(chunks) == 3
    assert chunks[0].metadata["strategy"] == "paragraph_fallback"


def test_estimate_tokens_has_simple_nonzero_heuristic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") >= 2


def test_chunk_router_uses_registered_chunker():
    html = {"content": "<ul><li>No smoking</li></ul>"}
    chunks = chunk_canonical_block(_block("guide_content.rules", html))
    assert len(chunks) == 1
    assert chunks[0].content_text == "No smoking"
