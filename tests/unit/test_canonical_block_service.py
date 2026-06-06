from __future__ import annotations

from uuid import UUID

from app.services.extraction.canonical_block_service import (
    CanonicalBlockService,
    _DocumentCorpusItem,
)


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROP_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PROP_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PROP_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def _block(render_type: str, data, *, block_id: int) -> dict:
    return {
        "id": block_id,
        "render_type": render_type,
        "title": "",
        "order": block_id,
        "data": data,
    }


def _page(page_id: int, title: str, blocks: list[dict]) -> dict:
    return {
        "id": page_id,
        "title": title,
        "sections": [
            {
                "id": page_id * 100,
                "title": title,
                "order": 1,
                "blocks": blocks,
            }
        ],
    }


def _doc(document_id: str, property_id: UUID, pages: list[dict]) -> _DocumentCorpusItem:
    return _DocumentCorpusItem(
        document_id=UUID(document_id),
        document_group_id=UUID(document_id),
        tenant_id=TENANT_ID,
        property_id=property_id,
        payload={"pages": pages},
    )


def _sample_corpus() -> list[_DocumentCorpusItem]:
    return [
        _doc(
            "00000000-0000-0000-0000-000000000001",
            PROP_A,
            [
                _page(
                    101,
                    "Welcome",
                    [
                        _block("guide_content.faqs", "<strong>FAQ</strong><p>Shared</p>", block_id=1),
                        _block("home.about_note", "<p>Unique about A</p>", block_id=2),
                        _block("widget.recommendations", [{"name": "Deferred"}], block_id=3),
                    ],
                ),
                _page(
                    102,
                    "Arrival",
                    [
                        _block("widget.reservation_info", {"check_in": "4pm", "check_out": "10am"}, block_id=4),
                        _block("widget.wifi", {"network": "A-WIFI", "password": "alpha"}, block_id=5),
                        _block("home.wifi_note", "Cluster wifi note", block_id=6),
                    ],
                ),
                _page(
                    103,
                    "General",
                    [
                        _block("home.about_note", "<p>Unique about A</p>", block_id=7),
                        _block("home.trash_info_note", "<p>Cluster trash one</p>", block_id=8),
                    ],
                ),
                _page(
                    104,
                    "FAQs",
                    [
                        _block("guide_content.faqs", "<strong>FAQ</strong><p>Shared</p>", block_id=9),
                    ],
                ),
            ],
        ),
        _doc(
            "00000000-0000-0000-0000-000000000002",
            PROP_B,
            [
                _page(
                    201,
                    "Welcome",
                    [
                        _block("guide_content.faqs", "<strong>FAQ</strong><p>Shared</p>", block_id=1),
                        _block("home.about_note", "<p>Unique about B</p>", block_id=2),
                    ],
                ),
                _page(
                    202,
                    "Arrival",
                    [
                        _block("widget.reservation_info", {"check_in": "4pm", "check_out": "10am"}, block_id=3),
                        _block("widget.wifi", {"network": "B-WIFI", "password": "bravo"}, block_id=4),
                        _block("home.wifi_note", "Cluster wifi note", block_id=5),
                    ],
                ),
                _page(
                    203,
                    "General",
                    [
                        _block("home.about_note", "<p>Unique about B</p>", block_id=6),
                        _block("home.trash_info_note", "<p>Cluster trash one</p>", block_id=7),
                    ],
                ),
                _page(
                    204,
                    "FAQs",
                    [
                        _block("guide_content.faqs", "<strong>FAQ</strong><p>Shared</p>", block_id=8),
                    ],
                ),
            ],
        ),
        _doc(
            "00000000-0000-0000-0000-000000000003",
            PROP_C,
            [
                _page(
                    301,
                    "Welcome",
                    [
                        _block("home.about_note", "<p>Unique about C</p>", block_id=1),
                    ],
                ),
                _page(
                    302,
                    "Arrival",
                    [
                        _block("widget.reservation_info", {"check_in": "3pm", "check_out": "10am"}, block_id=2),
                        _block("widget.wifi", {"network": "C-WIFI", "password": "charlie"}, block_id=3),
                        _block("home.wifi_note", "   ", block_id=4),
                        _block("home.direction_note", "<p>Turn left at the gate.</p>", block_id=5),
                    ],
                ),
                _page(
                    303,
                    "General",
                    [
                        _block("home.about_note", "<p>Unique about C</p>", block_id=6),
                        _block("home.trash_info_note", "<p>Unique trash C</p>", block_id=7),
                    ],
                ),
            ],
        ),
    ]


def test_tenant_scope_duplicates_collapse_to_single_canonical():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    blocks = manifest.canonical_blocks["guide_content.faqs"]
    assert len(blocks) == 1
    assert blocks[0].scope_type == "tenant"
    assert blocks[0].applicable_property_ids == [PROP_A, PROP_B, PROP_C]
    assert blocks[0].canonical_page_id == 104


def test_property_unique_blocks_remain_per_property():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    blocks = manifest.canonical_blocks["home.about_note"]
    assert len(blocks) == 3
    assert {block.canonical_source_property_id for block in blocks} == {PROP_A, PROP_B, PROP_C}
    assert {block.canonical_page_id for block in blocks} == {101, 201, 301}
    assert all(block.scope_type == "property" for block in blocks)


def test_clustered_blocks_keep_property_scope_with_group_metadata():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    blocks = manifest.canonical_blocks["widget.reservation_info"]
    assert len(blocks) == 3
    group_sizes = sorted(block.duplicate_group_metadata["member_count"] for block in blocks)
    assert group_sizes == [1, 2, 2]
    paired = [
        block
        for block in blocks
        if block.canonical_source_property_id in {PROP_A, PROP_B}
    ]
    assert len({block.duplicate_group_metadata["group_id"] for block in paired}) == 1
    assert paired[0].duplicate_group_metadata["member_property_ids"] == [PROP_A, PROP_B]


def test_empty_content_is_filtered_and_recorded():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    assert manifest.empty_content_property_ids["home.wifi_note"] == [PROP_C]
    blocks = manifest.canonical_blocks["home.wifi_note"]
    assert len(blocks) == 2
    assert {block.canonical_source_property_id for block in blocks} == {PROP_A, PROP_B}


def test_skip_rules_exclude_render_types():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    assert "widget.recommendations" not in manifest.canonical_blocks
    assert "widget.recommendations" in manifest.skip_render_types


def test_missing_tenant_block_still_applies_portfolio_wide():
    manifest = CanonicalBlockService().build_manifest_from_corpus(_sample_corpus())

    block = manifest.canonical_blocks["guide_content.faqs"][0]
    assert block.duplicate_count == 3
    assert block.applicable_property_ids == [PROP_A, PROP_B, PROP_C]
