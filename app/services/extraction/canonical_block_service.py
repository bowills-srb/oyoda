from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.storage import get_r2_client
from db.models.documents import DocumentModel


TENANT_SCOPE_RENDER_TYPES = {
    "guide_content.faqs",
    "guide_content.travel_tips",
    "guide_content.departure_instructions",
    "guide_content.rules",
    "widget.messaging_phone_number",
    "widget.phone_number",
    "widget.email_address",
    "widget.website",
}

PROPERTY_SCOPE_UNIQUE_RENDER_TYPES = {
    "home.about_note",
    "widget.wifi",
    "widget.getting_here",
    "home.direction_note",
}

CLUSTERED_RENDER_TYPES = {
    "widget.reservation_info",
    "home.trash_info_note",
    "home.wifi_note",
}

SKIP_RENDER_TYPES = {
    "widget.upsells",
    "guide_content.welcome_message",
    "guide_content.about_us",
    "widget.recommendations",
    "guide_content.safety_info",
}

CANONICAL_PAGE_MAPPING = {
    "home.about_note": "Welcome",
    "guide_content.faqs": "FAQs",
    "guide_content.departure_instructions": "General",
    "widget.wifi": "Arrival",
    "widget.reservation_info": "Arrival",
    "widget.getting_here": "Arrival",
    "home.trash_info_note": "General",
    "home.wifi_note": "Arrival",
}


@dataclass(frozen=True)
class CanonicalBlock:
    block_hash: str
    render_type: str
    tenant_id: UUID
    canonical_source_property_id: UUID
    canonical_page_id: int
    applicable_property_ids: list[UUID]
    scope_type: str
    duplicate_group_metadata: Optional[dict[str, Any]]
    duplicate_count: int
    block_content: dict[str, Any]


@dataclass(frozen=True)
class CanonicalBlockManifest:
    canonical_blocks: dict[str, list[CanonicalBlock]]
    duplicate_groups: dict[str, list[CanonicalBlock]]
    page_mapping: dict[str, str]
    skip_render_types: set[str]
    empty_content_property_ids: dict[str, list[UUID]]

    @property
    def total_canonical_blocks(self) -> int:
        return sum(len(items) for items in self.canonical_blocks.values())


@dataclass(frozen=True)
class _DocumentCorpusItem:
    document_id: UUID
    document_group_id: UUID
    tenant_id: UUID
    property_id: UUID
    payload: dict[str, Any]


@dataclass(frozen=True)
class _BlockOccurrence:
    tenant_id: UUID
    property_id: UUID
    page_id: int
    page_title: str
    block: dict[str, Any]
    block_hash: str
    normalized_content: str


def _normalize_block_content(block: dict[str, Any]) -> str:
    data = block.get("data")
    if data is None:
        return ""
    if isinstance(data, str):
        return data.strip()
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).strip()


def _content_hash(normalized_content: str) -> str:
    return hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()


def _group_id(render_type: str, block_hash: str) -> str:
    return f"{render_type.replace('.', '_')}_{block_hash[:12]}"


class CanonicalBlockService:
    def __init__(self) -> None:
        self.page_mapping = dict(CANONICAL_PAGE_MAPPING)
        self.skip_render_types = set(SKIP_RENDER_TYPES)

    async def build_manifest_for_portfolio(
        self,
        session: AsyncSession,
        tenant_id: UUID | str,
        document_ids: Optional[Iterable[UUID | str]] = None,
    ) -> CanonicalBlockManifest:
        corpus = await self._load_corpus(session, tenant_id=tenant_id, document_ids=document_ids)
        return self.build_manifest_from_corpus(corpus)

    async def _load_corpus(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID | str,
        document_ids: Optional[Iterable[UUID | str]],
    ) -> list[_DocumentCorpusItem]:
        tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
        stmt = (
            select(DocumentModel)
            .where(DocumentModel.tenant_id == tenant_uuid)
            .where(DocumentModel.document_type == "guidebook_api")
            .where(DocumentModel.extraction_status == "completed")
            .order_by(DocumentModel.property_id, DocumentModel.version_number.desc(), DocumentModel.uploaded_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        latest: dict[UUID, DocumentModel] = {}
        filter_ids: Optional[set[UUID]] = None
        if document_ids:
            filter_ids = {
                value if isinstance(value, UUID) else UUID(str(value))
                for value in document_ids
            }
        for row in rows:
            if row.property_id is None:
                continue
            if filter_ids is not None and row.id not in filter_ids:
                continue
            latest.setdefault(row.property_id, row)

        client = get_r2_client()
        corpus: list[_DocumentCorpusItem] = []
        for row in latest.values():
            manifest_bytes = await client.get_artifact(
                str(row.tenant_id),
                str(row.document_group_id),
                "guide_manifest.json",
                version=row._storage_version(),
            )
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not manifest.get("guide_token"):
                raise ValueError(f"guide_manifest.json missing guide_token for document {row.id}")
            raw_bytes = await row.get_content()
            payload = json.loads(raw_bytes.decode("utf-8"))
            corpus.append(
                _DocumentCorpusItem(
                    document_id=row.id,
                    document_group_id=row.document_group_id,
                    tenant_id=row.tenant_id,
                    property_id=row.property_id,
                    payload=payload,
                )
            )
        return corpus

    def build_manifest_from_corpus(
        self,
        corpus: Iterable[_DocumentCorpusItem],
    ) -> CanonicalBlockManifest:
        corpus_list = list(corpus)
        portfolio_property_ids = sorted({item.property_id for item in corpus_list}, key=str)
        empty_content_property_ids: dict[str, list[UUID]] = {}
        by_render_type: dict[str, list[_BlockOccurrence]] = {}

        for item in corpus_list:
            canonical_by_property_type = self._canonical_occurrences_for_property(item)
            for render_type, occurrence in canonical_by_property_type.items():
                if render_type in self.skip_render_types:
                    continue
                if not occurrence.normalized_content:
                    empty_content_property_ids.setdefault(render_type, []).append(item.property_id)
                    continue
                by_render_type.setdefault(render_type, []).append(occurrence)

        canonical_blocks: dict[str, list[CanonicalBlock]] = {}
        duplicate_groups: dict[str, list[CanonicalBlock]] = {}

        for render_type, occurrences in by_render_type.items():
            grouped = self._group_occurrences_by_hash(occurrences)
            if render_type in TENANT_SCOPE_RENDER_TYPES:
                canonical = self._build_tenant_scope_block(
                    render_type=render_type,
                    grouped=grouped,
                    portfolio_property_ids=portfolio_property_ids,
                )
                canonical_blocks[render_type] = [canonical]
                continue

            if render_type in PROPERTY_SCOPE_UNIQUE_RENDER_TYPES:
                blocks = [
                    CanonicalBlock(
                        block_hash=occurrence.block_hash,
                        render_type=render_type,
                        tenant_id=occurrence.tenant_id,
                        canonical_source_property_id=occurrence.property_id,
                        canonical_page_id=occurrence.page_id,
                        applicable_property_ids=[occurrence.property_id],
                        scope_type="property",
                        duplicate_group_metadata=None,
                        duplicate_count=1,
                        block_content=occurrence.block,
                    )
                    for occurrence in sorted(occurrences, key=lambda item: str(item.property_id))
                ]
                canonical_blocks[render_type] = blocks
                continue

            if render_type in CLUSTERED_RENDER_TYPES:
                blocks = self._build_clustered_blocks(render_type=render_type, grouped=grouped)
                canonical_blocks[render_type] = blocks
                for block in blocks:
                    if block.duplicate_group_metadata:
                        group_id = str(block.duplicate_group_metadata["group_id"])
                        duplicate_groups.setdefault(group_id, []).append(block)
                continue

            blocks = [
                CanonicalBlock(
                    block_hash=occurrence.block_hash,
                    render_type=render_type,
                    tenant_id=occurrence.tenant_id,
                    canonical_source_property_id=occurrence.property_id,
                    canonical_page_id=occurrence.page_id,
                    applicable_property_ids=[occurrence.property_id],
                    scope_type="property",
                    duplicate_group_metadata=None,
                    duplicate_count=1,
                    block_content=occurrence.block,
                )
                for occurrence in sorted(occurrences, key=lambda item: str(item.property_id))
            ]
            canonical_blocks[render_type] = blocks

        normalized_empty = {
            render_type: sorted(property_ids, key=str)
            for render_type, property_ids in empty_content_property_ids.items()
        }

        return CanonicalBlockManifest(
            canonical_blocks=canonical_blocks,
            duplicate_groups=duplicate_groups,
            page_mapping=dict(self.page_mapping),
            skip_render_types=set(self.skip_render_types),
            empty_content_property_ids=normalized_empty,
        )

    def _canonical_occurrences_for_property(
        self,
        item: _DocumentCorpusItem,
    ) -> dict[str, _BlockOccurrence]:
        by_render_type: dict[str, list[_BlockOccurrence]] = {}
        for page in item.payload.get("pages") or []:
            page_id = int(page.get("id") or 0)
            page_title = str(page.get("title") or "")
            for section in page.get("sections") or []:
                for block in section.get("blocks") or []:
                    render_type = str(block.get("render_type") or "unknown")
                    occurrence = _BlockOccurrence(
                        tenant_id=item.tenant_id,
                        property_id=item.property_id,
                        page_id=page_id,
                        page_title=page_title,
                        block=block,
                        block_hash=_content_hash(_normalize_block_content(block)),
                        normalized_content=_normalize_block_content(block),
                    )
                    by_render_type.setdefault(render_type, []).append(occurrence)

        canonical: dict[str, _BlockOccurrence] = {}
        for render_type, occurrences in by_render_type.items():
            canonical[render_type] = self._select_canonical_occurrence(render_type, occurrences)
        return canonical

    def _select_canonical_occurrence(
        self,
        render_type: str,
        occurrences: list[_BlockOccurrence],
    ) -> _BlockOccurrence:
        preferred_page = self.page_mapping.get(render_type)
        if preferred_page:
            for occurrence in occurrences:
                if occurrence.page_title == preferred_page:
                    return occurrence
        return sorted(occurrences, key=lambda item: (item.page_id, item.page_title))[0]

    def _group_occurrences_by_hash(
        self,
        occurrences: list[_BlockOccurrence],
    ) -> dict[str, list[_BlockOccurrence]]:
        grouped: dict[str, list[_BlockOccurrence]] = {}
        for occurrence in occurrences:
            grouped.setdefault(occurrence.block_hash, []).append(occurrence)
        for items in grouped.values():
            items.sort(key=lambda item: str(item.property_id))
        return grouped

    def _build_tenant_scope_block(
        self,
        *,
        render_type: str,
        grouped: dict[str, list[_BlockOccurrence]],
        portfolio_property_ids: list[UUID],
    ) -> CanonicalBlock:
        selected_hash, occurrences = sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), str(item[1][0].property_id)),
        )[0]
        occurrence = occurrences[0]
        return CanonicalBlock(
            block_hash=selected_hash,
            render_type=render_type,
            tenant_id=occurrence.tenant_id,
            canonical_source_property_id=occurrence.property_id,
            canonical_page_id=occurrence.page_id,
            applicable_property_ids=list(portfolio_property_ids),
            scope_type="tenant",
            duplicate_group_metadata=None,
            duplicate_count=len(portfolio_property_ids),
            block_content=occurrence.block,
        )

    def _build_clustered_blocks(
        self,
        *,
        render_type: str,
        grouped: dict[str, list[_BlockOccurrence]],
    ) -> list[CanonicalBlock]:
        blocks: list[CanonicalBlock] = []
        for block_hash, occurrences in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            member_property_ids = [occurrence.property_id for occurrence in occurrences]
            group_metadata = {
                "group_id": _group_id(render_type, block_hash),
                "member_property_ids": member_property_ids,
                "member_count": len(member_property_ids),
                "block_hash": block_hash,
            }
            for occurrence in occurrences:
                blocks.append(
                    CanonicalBlock(
                        block_hash=block_hash,
                        render_type=render_type,
                        tenant_id=occurrence.tenant_id,
                        canonical_source_property_id=occurrence.property_id,
                        canonical_page_id=occurrence.page_id,
                        applicable_property_ids=[occurrence.property_id],
                        scope_type="property",
                        duplicate_group_metadata=group_metadata,
                        duplicate_count=len(member_property_ids),
                        block_content=occurrence.block,
                    )
                )
        blocks.sort(key=lambda item: (item.render_type, str(item.canonical_source_property_id)))
        return blocks
