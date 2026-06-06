from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CanonicalPropertyWriteService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._schema_cache: Dict[str, set[str]] = {}

    async def sync_tenant_sources(self, tenant_id: UUID) -> Dict[str, int]:
        tenant = str(tenant_id)
        stats = {"properties": 0, "pms_listings": 0, "knowledge": 0, "profiles": 0}

        property_cols = await self._table_columns("properties")
        if property_cols:
            tenant_col = self._first_existing(property_cols, "tenant_id", "company_id")
            code_col = self._first_existing(property_cols, "property_code", "internal_code", "external_id", "property_external_id", "code")
            name_cols = [c for c in ("property_name", "name", "address_street", "address_line1", "community") if c in property_cols]
            json_cols = [c for c in ("external_ids", "extra_data") if c in property_cols]
            select_cols = [col for col in {code_col, "external_id", "address_street", "address_line1", "community", "property_name", "name", *json_cols} if col and col in property_cols]
            if tenant_col and code_col and select_cols:
                rows = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {', '.join(select_cols)}
                            FROM properties
                            WHERE {tenant_col} = CAST(:tid AS uuid)
                              {"AND deleted_at IS NULL" if "deleted_at" in property_cols else ""}
                            """
                        ),
                        {"tid": tenant},
                    )
                ).mappings().all()
                for row in rows:
                    canonical = str(row.get(code_col) or "").strip()
                    if not canonical:
                        continue
                    display_name = (
                        str(row.get("property_name") or "").strip()
                        or str(row.get("name") or "").strip()
                        or str(row.get("address_street") or "").strip()
                        or str(row.get("address_line1") or "").strip()
                        or canonical
                    )
                    marketing_name = (
                        str(row.get("property_name") or "").strip()
                        or str(row.get("name") or "").strip()
                    )
                    preferred_address = (
                        str(row.get("address_street") or "").strip()
                        or str(row.get("address_line1") or "").strip()
                    )
                    await self._upsert_profile(
                        tenant,
                        canonical,
                        display_name=display_name,
                        marketing_name=marketing_name,
                        preferred_address=preferred_address,
                        source="properties_sync",
                        metadata={"table": "properties"},
                    )
                    await self._upsert_ref(tenant, canonical, "internal", "property_code", canonical, "properties_sync", 1.0, {"table": "properties"})
                    external_id = str(row.get("external_id") or "").strip()
                    if external_id:
                        await self._upsert_ref(tenant, canonical, "internal", "external_id", external_id, "properties_sync", 0.98, {"table": "properties"})
                    provider_map = self._coerce_json_mapping(row.get("external_ids"))
                    extra_map = self._coerce_json_mapping(row.get("extra_data"))
                    provider_hint = str(
                        extra_map.get("provider_name")
                        or extra_map.get("pms_provider")
                        or "pms"
                    ).strip().lower() or "pms"
                    generic_identity_keys = {
                        "provider_account_id": "provider_account_id",
                        "provider_property_id": "property_id",
                        "provider_unit_id": "unit_id",
                        "provider_listing_id": "listing_id",
                    }
                    for source_key, ref_kind in generic_identity_keys.items():
                        ref_value = str(extra_map.get(source_key) or "").strip()
                        if ref_value:
                            await self._upsert_ref(
                                tenant,
                                canonical,
                                provider_hint,
                                ref_kind,
                                ref_value,
                                "properties_sync",
                                0.97,
                                {"table": "properties", "source_key": source_key},
                            )
                    provider_map.update(
                        {
                            key: value
                            for key, value in extra_map.items()
                            if key not in {"provider_name", "pms_provider", *generic_identity_keys.keys()}
                        }
                    )
                    for provider, value in provider_map.items():
                        ref = str(value or "").strip()
                        if not ref:
                            continue
                        if provider in {"airbnb_id", "vrbo_id", "listing_id", "pms_external_id"}:
                            derived_provider = "ota" if provider in {"airbnb_id", "vrbo_id", "listing_id"} else "pms"
                            derived_kind = "external_id"
                        else:
                            derived_provider = provider
                            derived_kind = "external_id"
                        await self._upsert_ref(
                            tenant,
                            canonical,
                            derived_provider,
                            derived_kind,
                            ref,
                            "properties_sync",
                            0.96,
                            {"table": "properties", "source_key": provider},
                        )
                    for col in name_cols:
                        value = str(row.get(col) or "").strip()
                        if value:
                            await self._upsert_ref(tenant, canonical, "internal", col, value, "properties_sync", 0.72 if col in {"community"} else 0.86, {"table": "properties"})
                    stats["properties"] += 1
                    stats["profiles"] += 1

        pms_cols = await self._table_columns("pms_listings")
        if pms_cols:
            tenant_col = self._first_existing(pms_cols, "company_id", "tenant_id")
            if tenant_col and "external_id" in pms_cols:
                select_cols = [col for col in ("external_id", "property_name", "pms_provider", "address_line1") if col in pms_cols]
                rows = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {', '.join(select_cols)}
                            FROM pms_listings
                            WHERE {tenant_col} = CAST(:tid AS uuid)
                              {"AND COALESCE(is_active, TRUE) = TRUE" if "is_active" in pms_cols else ""}
                            """
                        ),
                        {"tid": tenant},
                    )
                ).mappings().all()
                for row in rows:
                    canonical = str(row.get("external_id") or "").strip()
                    if not canonical:
                        continue
                    provider = str(row.get("pms_provider") or "pms").strip().lower() or "pms"
                    name = str(row.get("property_name") or "").strip()
                    addr = str(row.get("address_line1") or "").strip()
                    await self._upsert_profile(
                        tenant,
                        canonical,
                        display_name=name or addr or canonical,
                        marketing_name=name,
                        preferred_address=addr,
                        source="pms_sync",
                        metadata={"table": "pms_listings", "provider": provider},
                    )
                    await self._upsert_ref(tenant, canonical, provider, "external_id", canonical, "pms_sync", 1.0, {"table": "pms_listings"})
                    if name:
                        await self._upsert_ref(tenant, canonical, provider, "property_name", name, "pms_sync", 0.9, {"table": "pms_listings"})
                    if addr:
                        await self._upsert_ref(tenant, canonical, provider, "address_line1", addr, "pms_sync", 0.82, {"table": "pms_listings"})
                    stats["pms_listings"] += 1
                    stats["profiles"] += 1

        knowledge_cols = await self._table_columns("concierge_knowledge")
        if knowledge_cols:
            filters = ["tenant_id = CAST(:tid AS uuid)"]
            if "property_external_id" not in knowledge_cols:
                filters.append("FALSE")
            rows = (
                await self.session.execute(
                    text(
                        f"""
                        SELECT property_external_id
                        FROM concierge_knowledge
                        WHERE {' AND '.join(filters)}
                        """
                    ),
                    {"tid": tenant},
                )
            ).mappings().all()
            for row in rows:
                ext = str(row.get("property_external_id") or "").strip()
                if not ext or ext == "__all_properties__":
                    continue
                await self._upsert_ref(tenant, ext, "operator_kb", "property_external_id", ext, "concierge_knowledge", 0.94, {"table": "concierge_knowledge"})
                stats["knowledge"] += 1

        await self.session.commit()
        return stats

    async def register_property_record(
        self,
        tenant_id: UUID,
        *,
        canonical_property_code: str,
        display_name: Optional[str] = None,
        property_name: Optional[str] = None,
        address_line1: Optional[str] = None,
        external_ids: Optional[Dict[str, Any]] = None,
        aliases: Optional[Iterable[str]] = None,
        ref_pairs: Optional[Sequence[Dict[str, Any]]] = None,
        source: str = "system",
    ) -> None:
        tenant = str(tenant_id)
        canonical = (canonical_property_code or "").strip()
        if not canonical:
            return
        await self._upsert_profile(
            tenant,
            canonical,
            display_name=(display_name or property_name or address_line1 or canonical),
            marketing_name=property_name or display_name,
            preferred_address=address_line1,
            source=source,
            metadata={},
        )
        await self._upsert_ref(tenant, canonical, "internal", "property_code", canonical, source, 1.0, {})
        if property_name:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "property_name",
                property_name,
                source,
                0.92,
                {},
            )
        if address_line1:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "address_line1",
                address_line1,
                source,
                0.9,
                {},
            )
        for alias in aliases or []:
            value = str(alias or "").strip()
            if value:
                await self._upsert_ref(tenant, canonical, "internal", "alias", value, source, 0.9, {})
        for provider, value in (external_ids or {}).items():
            ref = str(value or "").strip()
            if ref:
                normalized_provider = str(provider).strip().lower()
                await self._upsert_ref(
                    tenant,
                    canonical,
                    normalized_provider,
                    "external_id",
                    ref,
                    source,
                    0.98,
                    {},
                )
                if normalized_provider == "pms":
                    await self._upsert_ref(
                        tenant,
                        canonical,
                        normalized_provider,
                        "unit_id",
                        ref,
                        source,
                        0.96,
                        {},
                    )
        for ref in ref_pairs or []:
            provider = str(ref.get("provider") or "internal").strip().lower() or "internal"
            ref_kind = str(ref.get("ref_kind") or "alias").strip() or "alias"
            ref_value = str(ref.get("ref_value") or "").strip()
            if not ref_value:
                continue
            confidence = float(ref.get("confidence") or 0.9)
            metadata = ref.get("metadata") or {}
            await self._upsert_ref(
                tenant,
                canonical,
                provider,
                ref_kind,
                ref_value,
                source,
                confidence,
                metadata,
            )
        await self.session.commit()

    async def link_property_identity(
        self,
        tenant_id: UUID,
        *,
        canonical_property_code: str,
        ref_value: str,
        provider: str = "internal",
        ref_kind: str = "alias",
        source: str = "manual_property_link",
        confidence: float = 0.99,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        tenant = str(tenant_id)
        canonical = (canonical_property_code or "").strip()
        value = (ref_value or "").strip()
        if not canonical or not value:
            return
        if display_name:
            await self._upsert_profile(
                tenant,
                canonical,
                display_name=display_name,
                marketing_name=display_name,
                preferred_address="",
                source=source,
                metadata=metadata or {},
            )
        await self._upsert_ref(
            tenant,
            canonical,
            provider.strip().lower() or "internal",
            ref_kind.strip() or "alias",
            value,
            source,
            confidence,
            metadata or {},
        )
        await self.session.commit()

    async def upsert_property_profile(
        self,
        tenant_id: UUID,
        *,
        canonical_property_code: str,
        display_name: Optional[str] = None,
        marketing_name: Optional[str] = None,
        preferred_address: Optional[str] = None,
        source: str = "manual_profile_update",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        tenant = str(tenant_id)
        canonical = (canonical_property_code or "").strip()
        if not canonical:
            return
        await self._upsert_profile(
            tenant,
            canonical,
            display_name=display_name or canonical,
            marketing_name=marketing_name or display_name,
            preferred_address=preferred_address,
            source=source,
            metadata=metadata or {},
        )
        if display_name:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "display_name",
                display_name,
                source,
                0.99,
                metadata or {},
            )
        if marketing_name and marketing_name != display_name:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "property_name",
                marketing_name,
                source,
                0.98,
                metadata or {},
            )
        await self.session.commit()

    async def observe_resolved_identity(
        self,
        tenant_id: UUID,
        *,
        canonical_property_code: str,
        platform: str = "",
        platform_listing_id: str = "",
        platform_unit_id: str = "",
        property_name: str = "",
        display_name: str = "",
        address_line1: str = "",
        source: str = "auto_identity_observation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        tenant = str(tenant_id)
        canonical = (canonical_property_code or "").strip()
        if not canonical:
            return

        normalized_platform = self._normalize_provider(platform)
        merged_metadata = dict(metadata or {})
        if normalized_platform:
            merged_metadata.setdefault("platform", normalized_platform)

        await self._upsert_profile(
            tenant,
            canonical,
            display_name=display_name or property_name or address_line1 or canonical,
            marketing_name=property_name or display_name,
            preferred_address=address_line1,
            source=source,
            metadata=merged_metadata,
        )

        if display_name:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "display_name",
                display_name,
                source,
                0.97,
                merged_metadata,
            )
        if property_name:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "property_name",
                property_name,
                source,
                0.95,
                merged_metadata,
            )
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "alias",
                property_name,
                source,
                0.94,
                merged_metadata,
            )
        if address_line1:
            await self._upsert_ref(
                tenant,
                canonical,
                "internal",
                "address_line1",
                address_line1,
                source,
                0.9,
                merged_metadata,
            )
        if platform_listing_id:
            provider = normalized_platform or "ota"
            await self._upsert_ref(
                tenant,
                canonical,
                provider,
                "external_id",
                platform_listing_id,
                source,
                0.99,
                merged_metadata,
            )
            await self._upsert_ref(
                tenant,
                canonical,
                provider,
                "listing_id",
                platform_listing_id,
                source,
                0.99,
                merged_metadata,
            )
        if platform_unit_id:
            provider = normalized_platform or "ota"
            await self._upsert_ref(
                tenant,
                canonical,
                provider,
                "unit_id",
                platform_unit_id,
                source,
                0.99,
                merged_metadata,
            )
            await self._upsert_ref(
                tenant,
                canonical,
                "pms",
                "unit_id",
                platform_unit_id,
                source,
                0.99,
                merged_metadata,
        )
        await self.session.commit()

    async def queue_property_link_review(
        self,
        tenant_id: UUID,
        *,
        canonical_property_code: str = "",
        provider: str = "internal",
        ref_kind: str = "alias",
        ref_value: str,
        platform_listing_id: str = "",
        platform_unit_id: str = "",
        property_name: str = "",
        display_name: str = "",
        confidence: float = 0.0,
        source: str = "property_link_review",
        candidates: Optional[Sequence[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        tenant = str(tenant_id)
        value = (ref_value or "").strip()
        if not value:
            return
        await self.session.execute(
            text(
                """
                INSERT INTO canonical_property_link_reviews (
                    tenant_id, canonical_property_code, provider, ref_kind,
                    ref_value, normalized_ref_value, platform_listing_id, platform_unit_id,
                    property_name, display_name, confidence, status, source,
                    candidate_payload, metadata
                )
                VALUES (
                    CAST(:tid AS uuid), NULLIF(:canonical, ''), :provider, :ref_kind,
                    :ref_value, :normalized, NULLIF(:platform_listing_id, ''), NULLIF(:platform_unit_id, ''),
                    NULLIF(:property_name, ''), NULLIF(:display_name, ''), :confidence, 'pending', :source,
                    CAST(:candidate_payload AS jsonb), CAST(:metadata AS jsonb)
                )
                ON CONFLICT (tenant_id, provider, ref_kind, normalized_ref_value, status)
                DO UPDATE SET
                    canonical_property_code = COALESCE(NULLIF(EXCLUDED.canonical_property_code, ''), canonical_property_link_reviews.canonical_property_code),
                    platform_listing_id = COALESCE(EXCLUDED.platform_listing_id, canonical_property_link_reviews.platform_listing_id),
                    platform_unit_id = COALESCE(EXCLUDED.platform_unit_id, canonical_property_link_reviews.platform_unit_id),
                    property_name = COALESCE(EXCLUDED.property_name, canonical_property_link_reviews.property_name),
                    display_name = COALESCE(EXCLUDED.display_name, canonical_property_link_reviews.display_name),
                    confidence = GREATEST(canonical_property_link_reviews.confidence, EXCLUDED.confidence),
                    source = EXCLUDED.source,
                    candidate_payload = EXCLUDED.candidate_payload,
                    metadata = canonical_property_link_reviews.metadata || EXCLUDED.metadata,
                    updated_at = NOW()
                """
            ),
            {
                "tid": tenant,
                "canonical": (canonical_property_code or "").strip(),
                "provider": self._normalize_provider(provider) or "internal",
                "ref_kind": (ref_kind or "alias").strip(),
                "ref_value": value,
                "normalized": value.casefold().strip(),
                "platform_listing_id": (platform_listing_id or "").strip(),
                "platform_unit_id": (platform_unit_id or "").strip(),
                "property_name": (property_name or "").strip(),
                "display_name": (display_name or "").strip(),
                "confidence": confidence,
                "source": source,
                "candidate_payload": json.dumps(list(candidates or [])),
                "metadata": json.dumps(metadata or {}),
            },
        )
        await self.session.commit()

    async def approve_property_link_review(
        self,
        tenant_id: UUID,
        *,
        review_id: int,
        canonical_property_code: str,
        approved_by: str = "",
    ) -> None:
        tenant = str(tenant_id)
        row = (
            await self.session.execute(
                text(
                    """
                    SELECT provider, ref_kind, ref_value, platform_listing_id, platform_unit_id,
                           property_name, display_name, metadata
                    FROM canonical_property_link_reviews
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND review_id = :review_id
                      AND status = 'pending'
                    LIMIT 1
                    """
                ),
                {"tid": tenant, "review_id": review_id},
            )
        ).mappings().first()
        if not row:
            return

        await self.observe_resolved_identity(
            tenant_id,
            canonical_property_code=canonical_property_code,
            platform=row.get("provider") or "",
            platform_listing_id=str(row.get("platform_listing_id") or ""),
            platform_unit_id=str(row.get("platform_unit_id") or ""),
            property_name=str(row.get("property_name") or ""),
            display_name=str(row.get("display_name") or ""),
            source="property_link_review_approved",
            metadata={**(row.get("metadata") or {}), "approved_by": approved_by},
        )
        await self.link_property_identity(
            tenant_id,
            canonical_property_code=canonical_property_code,
            ref_value=str(row.get("ref_value") or ""),
            provider=str(row.get("provider") or "internal"),
            ref_kind=str(row.get("ref_kind") or "alias"),
            source="property_link_review_approved",
            confidence=1.0,
            display_name=str(row.get("display_name") or ""),
            metadata={**(row.get("metadata") or {}), "approved_by": approved_by},
        )
        await self.session.execute(
            text(
                """
                UPDATE canonical_property_link_reviews
                SET canonical_property_code = :canonical,
                    status = 'approved',
                    updated_at = NOW(),
                    metadata = metadata || CAST(:metadata AS jsonb)
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND review_id = :review_id
                """
            ),
            {
                "tid": tenant,
                "review_id": review_id,
                "canonical": canonical_property_code,
                "metadata": json.dumps({"approved_by": approved_by}),
            },
        )
        await self.session.commit()

    async def reject_property_link_review(
        self,
        tenant_id: UUID,
        *,
        review_id: int,
        rejected_by: str = "",
    ) -> None:
        tenant = str(tenant_id)
        await self.session.execute(
            text(
                """
                UPDATE canonical_property_link_reviews
                SET status = 'rejected',
                    updated_at = NOW(),
                    metadata = metadata || CAST(:metadata AS jsonb)
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND review_id = :review_id
                  AND status = 'pending'
                """
            ),
            {
                "tid": tenant,
                "review_id": review_id,
                "metadata": json.dumps({"rejected_by": rejected_by}),
            },
        )
        await self.session.commit()

    async def _upsert_ref(
        self,
        tenant_id: str,
        canonical_property_code: str,
        provider: str,
        ref_kind: str,
        ref_value: str,
        source: str,
        confidence: float,
        metadata: Dict[str, Any],
    ) -> None:
        value = (ref_value or "").strip()
        if not value:
            return
        normalized = value.casefold().strip()
        await self.session.execute(
            text(
                """
                INSERT INTO canonical_property_refs (
                    tenant_id, canonical_property_code, provider, ref_kind,
                    ref_value, normalized_ref_value, source, confidence, metadata
                )
                VALUES (
                    CAST(:tid AS uuid), :canonical, :provider, :ref_kind,
                    :ref_value, :normalized, :source, :confidence, CAST(:metadata AS jsonb)
                )
                ON CONFLICT (tenant_id, provider, ref_kind, normalized_ref_value)
                DO UPDATE SET
                    canonical_property_code = EXCLUDED.canonical_property_code,
                    ref_value = EXCLUDED.ref_value,
                    source = EXCLUDED.source,
                    confidence = GREATEST(canonical_property_refs.confidence, EXCLUDED.confidence),
                    metadata = canonical_property_refs.metadata || EXCLUDED.metadata,
                    updated_at = NOW()
                """
            ),
            {
                "tid": tenant_id,
                "canonical": canonical_property_code,
                "provider": provider,
                "ref_kind": ref_kind,
                "ref_value": value,
                "normalized": normalized,
                "source": source,
                "confidence": confidence,
                "metadata": json.dumps(metadata or {}),
            },
        )

    async def _upsert_profile(
        self,
        tenant_id: str,
        canonical_property_code: str,
        *,
        display_name: Optional[str],
        marketing_name: Optional[str],
        preferred_address: Optional[str],
        source: str,
        metadata: Dict[str, Any],
    ) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO canonical_property_profiles (
                    tenant_id, canonical_property_code, display_name, marketing_name,
                    preferred_address, source, metadata
                )
                VALUES (
                    CAST(:tid AS uuid), :canonical, NULLIF(:display_name, ''),
                    NULLIF(:marketing_name, ''), NULLIF(:preferred_address, ''),
                    :source, CAST(:metadata AS jsonb)
                )
                ON CONFLICT (tenant_id, canonical_property_code)
                DO UPDATE SET
                    display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), canonical_property_profiles.display_name),
                    marketing_name = COALESCE(NULLIF(EXCLUDED.marketing_name, ''), canonical_property_profiles.marketing_name),
                    preferred_address = COALESCE(NULLIF(EXCLUDED.preferred_address, ''), canonical_property_profiles.preferred_address),
                    source = EXCLUDED.source,
                    metadata = canonical_property_profiles.metadata || EXCLUDED.metadata,
                    updated_at = NOW()
                """
            ),
            {
                "tid": tenant_id,
                "canonical": canonical_property_code,
                "display_name": (display_name or "").strip(),
                "marketing_name": (marketing_name or "").strip(),
                "preferred_address": (preferred_address or "").strip(),
                "source": source,
                "metadata": json.dumps(metadata or {}),
            },
        )

    async def _table_columns(self, table_name: str) -> set[str]:
        if table_name in self._schema_cache:
            return self._schema_cache[table_name]
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
        ).fetchall()
        cols = {str(row[0]) for row in rows}
        self._schema_cache[table_name] = cols
        return cols

    @staticmethod
    def _first_existing(columns: set[str], *candidates: str) -> Optional[str]:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    @staticmethod
    def _coerce_json_mapping(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except Exception:
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return {}

    @staticmethod
    def _normalize_provider(value: str) -> str:
        provider = (value or "").strip().lower()
        if provider in {"google", "gmail"}:
            return "gmail"
        if provider in {"outlook", "office365", "m365"}:
            return "microsoft"
        return provider


def get_canonical_property_write_service(session: AsyncSession) -> CanonicalPropertyWriteService:
    return CanonicalPropertyWriteService(session)
