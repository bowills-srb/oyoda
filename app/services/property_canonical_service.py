from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
    get_scoped_knowledge_service,
    project_to_legacy_concierge_knowledge_shape,
)
from app.services.operator_policies.discount_rules import (
    default_operator_policies,
    normalize_operator_policies,
)

logger = logging.getLogger(__name__)


class CanonicalPropertyService:
    """
    Canonical property intelligence for messaging.

    Messaging should read from one merged profile, regardless of whether
    facts came from:
      - operator-managed property rows
      - PMS listing sync
      - operator KB / concierge knowledge
    """

    _TOKEN_SCORE_BIND_THRESHOLD = 0.45
    _TOKEN_SCORE_MARGIN_THRESHOLD = 0.15

    def __init__(self, session: AsyncSession):
        self.session = session
        self._schema_cache: Dict[str, set[str]] = {}

    async def _load_operator_policies(
        self,
        tenant_id: UUID,
        *,
        property_row: Optional[Dict[str, Any]] = None,
        property_pet_friendly: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Load tenant policies and merge per-property overrides.

        Property-level allow/deny is authoritative for pet acceptance.
        Tenant-level pet fields remain available only as backward-compat
        data until later cleanup phases.
        """
        if self.session is None:
            defaults = default_operator_policies()
            defaults["_source_provenance"] = {
                key: "schema_default"
                for key in defaults
                if not key.startswith("_")
            }
            if property_pet_friendly is not None:
                defaults["pet_policy"] = "allowed" if property_pet_friendly else "not_allowed"
                defaults["_source_provenance"]["pet_policy"] = "property_fact"
            return defaults

        try:
            row = (
                await self.session.execute(
                    text(
                        """
                        SELECT
                            tenant_id,
                            check_in_time,
                            check_out_time,
                            late_checkout_available,
                            late_checkout_max_time,
                            late_checkout_fee,
                            late_checkout_requires_approval,
                            early_checkin_available,
                            early_checkin_earliest,
                            early_checkin_fee,
                            early_checkin_subject_to_availability,
                            cancellation_full_refund_days,
                            cancellation_partial_refund_days,
                            cancellation_partial_refund_percent,
                            pets_allowed,
                            pet_fee,
                            pet_max_weight,
                            pet_restricted_breeds,
                            pet_notes,
                            pool_heat_available,
                            pool_heat_daily_fee,
                            pool_heat_advance_notice_hours,
                            beach_chairs_included,
                            beach_chair_rental_partners,
                            discount_policies,
                            additional_policies,
                            support_phone,
                            support_email,
                            emergency_phone
                        FROM operator_policies
                        WHERE tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": str(tenant_id)},
                )
            ).mappings().first()
            merged = normalize_operator_policies(dict(row) if row else None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[CanonicalPropertyService] operator_policies load failed: tenant=%s error=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            merged = default_operator_policies()
            merged["_load_error"] = True

        source_provenance = {
            key: ("operator_default" if merged.get("_authored", False) else "schema_default")
            for key in merged
            if not key.startswith("_")
        }

        overrides: Dict[str, Any] = {}
        if property_row:
            overrides = self._dictish(property_row.get("property_policy_overrides"))
        if overrides:
            for key, value in overrides.items():
                if value is None:
                    continue
                merged[key] = value
                source_provenance[key] = "property_override"

        if property_pet_friendly is not None:
            merged["pet_policy"] = "allowed" if property_pet_friendly else "not_allowed"
            source_provenance["pet_policy"] = "property_fact"

        merged["_source_provenance"] = source_provenance
        return merged

    @staticmethod
    def _ci_text_expr(column: str) -> str:
        """Build a case-insensitive text expression for dynamic schema columns."""
        return f"LOWER(({column})::text)"

    @staticmethod
    def _external_hint_variants(external_hint: str) -> List[str]:
        values: List[str] = []
        normalized = (external_hint or "").strip()
        if not normalized:
            return values
        values.append(normalized)
        if "-" in normalized:
            suffix = normalized.rsplit("-", 1)[-1].strip()
            if suffix and suffix not in values:
                values.append(suffix)
        return values

    async def resolve_property_code(
        self,
        tenant_id: UUID,
        *,
        platform_listing_id: str = "",
        platform_unit_id: str = "",
        property_name: str = "",
        platform: str = "",
    ) -> str:
        tenant = str(tenant_id)
        ref_candidates = []
        if platform_listing_id:
            ref_candidates.append((platform.lower() or "ota", "external_id", platform_listing_id))
            ref_candidates.append((platform.lower() or "ota", "listing_id", platform_listing_id))
            ref_candidates.append(("ota", "external_id", platform_listing_id))
            ref_candidates.append(("ota", "listing_id", platform_listing_id))
        if platform_unit_id:
            ref_candidates.append((platform.lower() or "ota", "unit_id", platform_unit_id))
            ref_candidates.append(("ota", "unit_id", platform_unit_id))
            ref_candidates.append(("pms", "unit_id", platform_unit_id))
        if property_name:
            if property_name.startswith("ExternalID:"):
                external_hint = property_name.split(":", 1)[1].strip()
                if external_hint:
                    ref_candidates.append(("pms", "property_id", external_hint))
                    ref_candidates.append(("internal", "external_id", external_hint))
                    for suffix in self._external_hint_variants(external_hint)[1:]:
                        ref_candidates.append(("pms", "property_id", suffix))
                        ref_candidates.append(("pms", "external_id", suffix))
                        ref_candidates.append(("internal", "external_id", suffix))
                        ref_candidates.append(("internal", "alias", suffix))
            ref_candidates.append(("internal", "display_name", property_name))
            ref_candidates.append(("internal", "property_name", property_name))
            ref_candidates.append(("internal", "address_street", property_name))
            ref_candidates.append(("internal", "address_line1", property_name))
            ref_candidates.append(("internal", "alias", property_name))
        direct_ref = await self._resolve_from_canonical_refs(tenant, ref_candidates)
        if direct_ref:
            return direct_ref

        property_meta = await self._property_table_meta()
        pms_meta = await self._pms_table_meta()
        property_cols = property_meta["columns"]

        def property_scope() -> str:
            parts: List[str] = []
            if property_meta["tenant_col"]:
                parts.append(f"{property_meta['tenant_col']}::text = :op")
            if "deleted_at" in property_cols:
                parts.append("deleted_at IS NULL")
            if "is_deleted" in property_cols:
                parts.append("COALESCE(is_deleted, FALSE) = FALSE")
            return " AND ".join(parts) if parts else "TRUE"

        def pms_scope() -> str:
            parts: List[str] = []
            if pms_meta["tenant_col"]:
                parts.append(f"{pms_meta['tenant_col']}::text = :op")
            if "is_active" in pms_meta["columns"]:
                parts.append("COALESCE(is_active, TRUE) = TRUE")
            return " AND ".join(parts) if parts else "TRUE"

        async def resolve_from_properties(matchers: List[str], params: Dict[str, Any]) -> str:
            canonical = property_meta["canonical_code_col"]
            if not canonical or not matchers:
                return ""
            row = (
                await self.session.execute(
                    text(
                        f"""
                        SELECT {canonical}
                        FROM properties
                        WHERE {property_scope()}
                          AND ({' OR '.join(matchers)})
                        LIMIT 1
                        """
                    ),
                    params,
                )
            ).fetchone()
            return str(row[0]) if row and row[0] is not None else ""

        if platform_listing_id:
            matchers = [f"{col} = :listing_id" for col in property_meta["code_cols"]]
            if property_meta["json_external_ids_col"]:
                matchers.append(
                    f"COALESCE({property_meta['json_external_ids_col']} ->> :platform, '') = :listing_id"
                )
            if property_meta["json_extra_col"]:
                extra = property_meta["json_extra_col"]
                matchers.extend(
                    [
                        f"COALESCE({extra} ->> 'listing_id', '') = :listing_id",
                        f"COALESCE({extra} ->> 'vrbo_id', '') = :listing_id",
                        f"COALESCE({extra} ->> 'airbnb_id', '') = :listing_id",
                        f"COALESCE({extra} ->> 'pms_external_id', '') = :listing_id",
                    ]
                )
            resolved = await resolve_from_properties(
                matchers,
                {"op": tenant, "listing_id": platform_listing_id, "platform": platform},
            )
            if resolved:
                return resolved

            if pms_meta["canonical_code_col"] and pms_meta["listing_id_cols"]:
                listing_matchers = [
                    f"COALESCE({col}, '') = :listing_id"
                    for col in pms_meta["listing_id_cols"]
                ]
                row = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {pms_meta['canonical_code_col']}
                            FROM pms_listings
                            WHERE {pms_scope()}
                              AND ({' OR '.join(listing_matchers)})
                            LIMIT 1
                            """
                        ),
                        {"op": tenant, "listing_id": platform_listing_id},
                    )
                ).fetchone()
                if row and row[0]:
                    return str(row[0])

            alias_cols = await self._table_columns("listing_id_aliases")
            if alias_cols:
                alias_row = (
                    await self.session.execute(
                        text(
                            """
                            SELECT canonical_external_id
                            FROM listing_id_aliases
                            WHERE company_id::text = :op
                              AND alias_external_id = :listing_id
                            LIMIT 1
                            """
                        ),
                        {"op": tenant, "listing_id": platform_listing_id},
                    )
                ).fetchone()
                if alias_row and alias_row[0]:
                    return str(alias_row[0])

            if pms_meta["canonical_code_col"]:
                row = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {pms_meta['canonical_code_col']}
                            FROM pms_listings
                            WHERE {pms_scope()}
                              AND {pms_meta['canonical_code_col']} = :listing_id
                            LIMIT 1
                            """
                        ),
                        {"op": tenant, "listing_id": platform_listing_id},
                    )
                ).fetchone()
                if row and row[0]:
                    return str(row[0])

        if platform_unit_id:
            matchers = [f"{col} = :unit_id" for col in property_meta["code_cols"]]
            if property_meta["json_external_ids_col"]:
                matchers.append(
                    f"COALESCE({property_meta['json_external_ids_col']} ->> 'pms', '') = :unit_id"
                )
            if property_meta["json_extra_col"]:
                extra = property_meta["json_extra_col"]
                matchers.extend(
                    [
                        f"COALESCE({extra} ->> 'unit_id', '') = :unit_id",
                        f"COALESCE({extra} ->> 'unit_code', '') = :unit_id",
                    ]
                )
            resolved = await resolve_from_properties(matchers, {"op": tenant, "unit_id": platform_unit_id})
            if resolved:
                return resolved

            if pms_meta["canonical_code_col"] and pms_meta["unit_id_cols"]:
                unit_matchers = [
                    f"COALESCE({col}, '') = :unit_id"
                    for col in pms_meta["unit_id_cols"]
                ]
                row = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {pms_meta['canonical_code_col']}
                            FROM pms_listings
                            WHERE {pms_scope()}
                              AND ({' OR '.join(unit_matchers)})
                            LIMIT 1
                            """
                        ),
                        {"op": tenant, "unit_id": platform_unit_id},
                    )
                ).fetchone()
                if row and row[0]:
                    return str(row[0])

        if property_name.startswith("ExternalID:"):
            external_hint = property_name.split(":", 1)[1].strip()
            if external_hint:
                matchers = [f"{col} = :external_id" for col in property_meta["code_cols"]]
                if property_meta["json_external_ids_col"]:
                    ext = property_meta["json_external_ids_col"]
                    matchers.extend(
                        [
                            f"COALESCE({ext} ->> 'pms', '') = :external_id",
                            f"COALESCE({ext} ->> 'escapia', '') = :external_id",
                            f"COALESCE({ext} ->> 'airbnb', '') = :external_id",
                            f"COALESCE({ext} ->> 'vrbo', '') = :external_id",
                        ]
                    )
                if property_meta["json_extra_col"]:
                    extra = property_meta["json_extra_col"]
                    matchers.extend(
                        [
                            f"COALESCE({extra} ->> 'external_id', '') = :external_id",
                            f"COALESCE({extra} ->> 'pms_external_id', '') = :external_id",
                        ]
                    )
                for candidate_external_id in self._external_hint_variants(external_hint):
                    resolved = await resolve_from_properties(
                        matchers,
                        {"op": tenant, "external_id": candidate_external_id},
                    )
                    if resolved:
                        return resolved
                    if pms_meta["canonical_code_col"] and "external_id" in pms_meta["columns"]:
                        row = (
                            await self.session.execute(
                                text(
                                    f"""
                                    SELECT {pms_meta['canonical_code_col']}
                                    FROM pms_listings
                                    WHERE {pms_scope()}
                                      AND COALESCE(external_id, '') = :external_id
                                    LIMIT 1
                                    """
                                ),
                                {"op": tenant, "external_id": candidate_external_id},
                            )
                        ).fetchone()
                        if row and row[0]:
                            return str(row[0])

        website_path_variants = self._website_path_variants(property_name)
        guide_url_col = property_meta["guide_url_col"]
        if guide_url_col and website_path_variants:
            for candidate_path in website_path_variants:
                row = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {property_meta['canonical_code_col']}
                            FROM properties
                            WHERE {property_scope()}
                              AND (
                                LOWER(COALESCE({guide_url_col}, '')) = LOWER(:path_exact)
                                OR LOWER(COALESCE({guide_url_col}, '')) LIKE LOWER(:path_suffix)
                              )
                            LIMIT 1
                            """
                        ),
                        {
                            "op": tenant,
                            "path_exact": candidate_path,
                            "path_suffix": f"%{candidate_path}",
                        },
                    )
                ).fetchone()
                if row and row[0]:
                    return str(row[0])

        if property_name:
            name_matchers = [
                f"{self._ci_text_expr(col)} = LOWER(:name)" for col in property_meta["name_cols"]
            ] + [
                f"{self._ci_text_expr(col)} LIKE LOWER(:name_fuzzy)" for col in property_meta["name_cols"]
            ]
            resolved = await resolve_from_properties(
                name_matchers,
                {"op": tenant, "name": property_name, "name_fuzzy": f"%{property_name[:20]}%"},
            )
            if resolved:
                return resolved
            if pms_meta["name_col"] and pms_meta["canonical_code_col"]:
                row = (
                    await self.session.execute(
                        text(
                            f"""
                            SELECT {pms_meta['canonical_code_col']}
                            FROM pms_listings
                            WHERE {pms_scope()}
                              AND (
                                {self._ci_text_expr(pms_meta['name_col'])} = LOWER(:name)
                                OR {self._ci_text_expr(pms_meta['name_col'])} LIKE LOWER(:name_fuzzy)
                              )
                            LIMIT 1
                            """
                        ),
                        {"op": tenant, "name": property_name, "name_fuzzy": f"%{property_name[:20]}%"},
                    )
                ).fetchone()
                if row and row[0]:
                    return str(row[0])

        # Existing tiers require the input to be near-identical to a stored
        # value. Guest free-text like "294 spartina circle" vs stored
        # "294 Spartina Cir" fails those, but token overlap is still
        # unambiguous because the street-number token is near-unique within a
        # tenant's address corpus. This tier runs only after all exact/LIKE
        # resolution paths above have failed, so it cannot change any lookup
        # that currently resolves successfully.
        if property_name:
            suggestions = await self.suggest_property_matches(
                tenant_id, property_name, limit=2
            )
            if suggestions:
                top = suggestions[0]
                top_score = float(top["score"])
                second_score = float(suggestions[1]["score"]) if len(suggestions) > 1 else 0.0
                margin = top_score - second_score
                if (
                    top_score >= self._TOKEN_SCORE_BIND_THRESHOLD
                    and margin >= self._TOKEN_SCORE_MARGIN_THRESHOLD
                ):
                    logger.info(
                        "[CanonicalResolver] token-score fallback bound "
                        "property_code=%s score=%.3f second=%.3f margin=%.3f matched_on=%s input=%r",
                        top["property_code"],
                        top_score,
                        second_score,
                        margin,
                        top.get("matched_on"),
                        property_name[:80],
                    )
                    return str(top["property_code"])
                logger.info(
                    "[CanonicalResolver] token-score fallback declined "
                    "property_code=%s score=%.3f second=%.3f margin=%.3f matched_on=%s input=%r",
                    top.get("property_code"),
                    top_score,
                    second_score,
                    margin,
                    top.get("matched_on"),
                    property_name[:80],
                )
        return ""

    async def _resolve_from_canonical_refs(
        self,
        tenant: str,
        candidates: List[tuple[str, str, str]],
    ) -> str:
        if not await self._table_columns("canonical_property_refs"):
            return ""
        seen = set()
        for provider, ref_kind, ref_value in candidates:
            normalized = (ref_value or "").strip().casefold()
            if not normalized:
                continue
            key = (provider, ref_kind, normalized)
            if key in seen:
                continue
            seen.add(key)
            row = (
                await self.session.execute(
                    text(
                        """
                        SELECT canonical_property_code
                        FROM canonical_property_refs
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND provider = :provider
                          AND ref_kind = :ref_kind
                          AND normalized_ref_value = :normalized
                        LIMIT 1
                        """
                    ),
                    {
                        "tid": tenant,
                        "provider": provider,
                        "ref_kind": ref_kind,
                        "normalized": normalized,
                    },
                )
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        return ""

    async def build_profile(
        self,
        tenant_id: UUID,
        *,
        property_code: str = "",
        property_name_hint: str = "",
    ) -> Dict[str, Any]:
        tenant = str(tenant_id)
        property_meta = await self._property_table_meta()
        property_cols = property_meta["columns"]
        pms_meta = await self._pms_table_meta()
        pms_cols = pms_meta["columns"]

        profile: Dict[str, Any] = {
            "property_name": property_name_hint or property_code,
            "display_name": property_name_hint or property_code,
            "property_external_id": property_code,
            "external_id": property_code,
            "preferred_address": "",
            "bedrooms": None,
            "bathrooms": None,
            "max_guests": None,
            "has_pool": False,
            "pool_heated": False,
            "has_hot_tub": False,
            "has_waterfront": False,
            "pet_friendly": None,
            "beach_access_type": "",
            "parking_summary": "",
            "wifi_available": False,
            "property_summary": "",
            "description": "",
            "community_name": "",
            "check_in_time": "",
            "check_out_time": "",
            "operator_policies": default_operator_policies(),
            "concierge_knowledge": {
                "property_context": {},
                "facts": {},
                "sections": {},
                "faq": [],
                "source": "",
            },
            "source_provenance": {},
        }

        prop_row = await self._load_property_row(tenant, property_code)
        if prop_row:
            amenities_col = property_meta["amenities_col"]
            extra_col = property_meta["json_extra_col"]
            amenities = self._dictish(prop_row.get(amenities_col)) if amenities_col else {}
            extra = self._dictish(prop_row.get(extra_col)) if extra_col else {}
            beach_access = amenities.get("beach_access") or extra.get("beach_access") or {}
            if isinstance(beach_access, str):
                beach_access = {"type": beach_access}
            property_name = next(
                (prop_row.get(col) for col in property_meta["name_cols"] if prop_row.get(col)),
                profile["property_name"],
            )
            description = ""
            if property_meta["description_col"]:
                description = str(prop_row.get(property_meta["description_col"]) or "").strip()
            community_name = str(prop_row.get("community") or extra.get("community_name") or "").strip()
            parking = (
                amenities.get("parking")
                or extra.get("parking")
                or prop_row.get("parking_instructions")
                or prop_row.get("parking_spaces")
                or ""
            )
            wifi_available = bool(
                prop_row.get("wifi_network")
                or amenities.get("wifi")
                or amenities.get("internet")
                or extra.get("wifi_network")
            )
            summary_bits = [bit for bit in [description[:320], f"Community: {community_name}" if community_name else ""] if bit]
            if isinstance(beach_access, dict) and beach_access.get("type"):
                summary_bits.append(f"Beach access: {beach_access.get('type')}")
            property_pet_friendly: Optional[bool] = None
            if "pets_allowed" in prop_row and prop_row.get("pets_allowed") is not None:
                property_pet_friendly = bool(prop_row.get("pets_allowed"))
            elif "pet_friendly" in amenities:
                property_pet_friendly = bool(amenities.get("pet_friendly"))
            profile.update(
                {
                    "property_name": property_name,
                    "display_name": property_name,
                    "property_external_id": str(prop_row.get(property_meta["canonical_code_col"]) or property_code),
                    "external_id": str(prop_row.get("external_id") or property_code),
                    "preferred_address": str(prop_row.get("address_street") or prop_row.get("address_line1") or ""),
                    "bedrooms": prop_row.get("bedrooms"),
                    "bathrooms": prop_row.get("bathrooms"),
                    "max_guests": prop_row.get("sleeps") or prop_row.get("max_occupancy"),
                    "has_pool": bool(prop_row.get("has_pool")) or bool(amenities.get("pool")),
                    "pool_heated": bool(prop_row.get("pool_heated")) or self._dictish(amenities.get("pool")).get("heated", False),
                    "has_hot_tub": bool(prop_row.get("has_hot_tub")) or bool(amenities.get("hot_tub")),
                    "has_waterfront": bool(amenities.get("waterfront")),
                    "pet_friendly": property_pet_friendly,
                    "beach_access_type": beach_access.get("type", "") if isinstance(beach_access, dict) else "",
                    "parking_summary": str(parking)[:120] if parking else "",
                    "wifi_available": wifi_available,
                    "property_summary": " | ".join(summary_bits)[:500],
                    "description": description[:500],
                    "community_name": community_name,
                    "check_in_time": str(prop_row.get("check_in_time") or extra.get("check_in_time") or ""),
                    "check_out_time": str(prop_row.get("check_out_time") or extra.get("check_out_time") or ""),
                }
            )
            profile["source_provenance"]["properties"] = True

        profile_row = await self._load_profile_row(tenant, profile["property_external_id"] or property_code)
        if profile_row:
            display_name = str(profile_row.get("display_name") or "").strip()
            marketing_name = str(profile_row.get("marketing_name") or "").strip()
            preferred_address = str(profile_row.get("preferred_address") or "").strip()
            if marketing_name:
                profile["property_name"] = marketing_name
            if display_name:
                profile["display_name"] = display_name
            else:
                profile["display_name"] = profile["property_name"]
            if preferred_address:
                profile["preferred_address"] = preferred_address
            if preferred_address and not profile["property_summary"]:
                profile["property_summary"] = preferred_address[:500]
            profile["source_provenance"]["canonical_profile"] = True
        else:
            profile["display_name"] = profile["property_name"]

        pms_row = await self._load_pms_row(tenant, profile["property_external_id"], profile["external_id"], profile["property_name"])
        if pms_row:
            pms_name = str(pms_row.get(pms_meta["name_col"]) or "")
            profile["property_name"] = profile["property_name"] or pms_name
            profile["display_name"] = profile["display_name"] or profile["property_name"] or pms_name
            profile["property_external_id"] = profile["property_external_id"] or str(pms_row.get("external_id") or property_code)
            profile["external_id"] = profile["external_id"] or str(pms_row.get("external_id") or property_code)
            profile["bedrooms"] = profile["bedrooms"] or pms_row.get("bedrooms")
            profile["bathrooms"] = profile["bathrooms"] or pms_row.get("bathrooms")
            profile["max_guests"] = profile["max_guests"] or pms_row.get("max_guests")
            profile["has_pool"] = bool(profile["has_pool"]) or bool(pms_row.get("has_pool"))
            profile["pool_heated"] = bool(profile["pool_heated"]) or bool(pms_row.get("pool_heated"))
            profile["has_hot_tub"] = bool(profile["has_hot_tub"]) or bool(pms_row.get("has_hot_tub"))
            profile["has_waterfront"] = bool(profile["has_waterfront"]) or bool(pms_row.get("has_waterfront"))
            if profile["pet_friendly"] is None and pms_row.get("pet_friendly") is not None:
                profile["pet_friendly"] = bool(pms_row.get("pet_friendly"))
            if not profile["beach_access_type"]:
                profile["beach_access_type"] = str(pms_row.get("beach_access") or pms_row.get("waterfront_type") or "")
            if not profile["property_summary"]:
                profile["property_summary"] = " | ".join(
                    bit
                    for bit in [
                        str(pms_row.get("property_name") or "").strip(),
                        str(pms_row.get("beach_access") or "").strip(),
                        str(pms_row.get("waterfront_type") or "").strip(),
                    ]
                    if bit
                )[:500]
            profile["source_provenance"]["pms_listings"] = True

        profile["operator_policies"] = await self._load_operator_policies(
            tenant_id,
            property_row=prop_row,
            property_pet_friendly=profile.get("pet_friendly"),
        )
        profile["source_provenance"]["operator_policies"] = dict(
            profile["operator_policies"].get("_source_provenance") or {}
        )
        profile["source_provenance"]["operator_policies_authored"] = bool(
            profile["operator_policies"].get("_authored", False)
        )

        knowledge = await self._load_concierge_knowledge(tenant_id, prop_row, profile["property_external_id"])
        if knowledge:
            facts = self._dictish(knowledge.get("facts"))
            sections = self._dictish(knowledge.get("sections"))
            property_context = self._dictish(knowledge.get("property_context"))
            faq = knowledge.get("faq") if isinstance(knowledge.get("faq"), list) else []
            profile["concierge_knowledge"] = {
                "property_context": property_context,
                "facts": facts,
                "sections": sections,
                "faq": faq,
                "source": str(knowledge.get("source") or ""),
            }
            profile["source_provenance"]["concierge_knowledge"] = True
            if knowledge.get("retrieval_source"):
                profile["source_provenance"]["concierge_knowledge_retrieval_source"] = str(
                    knowledge.get("retrieval_source") or ""
                )

            if not profile["check_in_time"] and facts.get("check_in"):
                profile["check_in_time"] = str(facts.get("check_in"))
            if not profile["check_out_time"] and facts.get("check_out"):
                profile["check_out_time"] = str(facts.get("check_out"))
            if not profile["wifi_available"] and facts.get("wifi"):
                profile["wifi_available"] = True
            if not profile["parking_summary"] and facts.get("parking"):
                profile["parking_summary"] = str(facts.get("parking"))[:120]
            if not profile["beach_access_type"] and facts.get("beach_access"):
                profile["beach_access_type"] = str(facts.get("beach_access"))[:120]
            if not profile["description"] and sections.get("overview"):
                profile["description"] = str(sections.get("overview"))[:500]
            if not profile["property_summary"]:
                summary_bits = [
                    str(property_context.get("headline") or "").strip(),
                    str(sections.get("overview") or "").strip()[:240],
                ]
                profile["property_summary"] = " | ".join(bit for bit in summary_bits if bit)[:500]
            profile["display_name"] = profile["display_name"] or profile["property_name"]

        return profile

    async def suggest_property_matches(
        self,
        tenant_id: UUID,
        raw_value: str,
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        query = (raw_value or "").strip()
        if not query:
            return []

        tenant = str(tenant_id)
        property_meta = await self._property_table_meta()
        canonical_col = property_meta["canonical_code_col"]
        if not canonical_col:
            return []

        prop_rows = await self._load_property_candidates(tenant, property_meta)
        refs_by_code = await self._load_ref_candidates(tenant)
        query_norm = self._normalize_value(query)
        query_tokens = self._tokenize(query)

        suggestions: List[Dict[str, Any]] = []
        for row in prop_rows:
            property_code = str(row.get(canonical_col) or "").strip()
            if not property_code:
                continue

            labels = []
            seen = set()
            for col in property_meta["name_cols"]:
                value = str(row.get(col) or "").strip()
                if value and value.casefold() not in seen:
                    labels.append({"value": value, "kind": col})
                    seen.add(value.casefold())
            for ref in refs_by_code.get(property_code, []):
                value = str(ref.get("ref_value") or "").strip()
                if value and value.casefold() not in seen:
                    labels.append({"value": value, "kind": ref.get("ref_kind") or "alias"})
                    seen.add(value.casefold())

            best_score = 0.0
            matched_on = ""
            matched_value = ""
            for label in labels:
                score = self._match_score(query_norm, query_tokens, label["value"])
                if score > best_score:
                    best_score = score
                    matched_on = str(label["kind"])
                    matched_value = str(label["value"])
            if best_score <= 0:
                continue

            suggestions.append(
                {
                    "property_code": property_code,
                    "property_name": next(
                        (str(row.get(col) or "").strip() for col in property_meta["name_cols"] if row.get(col)),
                        property_code,
                    ),
                    "address_street": str(row.get("address_street") or row.get("address_line1") or "").strip(),
                    "community": str(row.get("community") or "").strip(),
                    "external_id": str(row.get("external_id") or "").strip(),
                    "score": round(best_score, 4),
                    "matched_on": matched_on,
                    "matched_value": matched_value,
                }
            )

        suggestions.sort(key=lambda item: (-float(item["score"]), item["property_name"], item["property_code"]))
        return suggestions[: max(1, limit)]

    async def _load_property_row(self, tenant: str, property_code: str) -> Optional[Dict[str, Any]]:
        meta = await self._property_table_meta()
        columns = meta["columns"]
        canonical = meta["canonical_code_col"]
        if not canonical or not property_code:
            return None
        scope = []
        if meta["tenant_col"]:
            scope.append(f"{meta['tenant_col']}::text = :op")
        if "deleted_at" in columns:
            scope.append("deleted_at IS NULL")
        if "is_deleted" in columns:
            scope.append("COALESCE(is_deleted, FALSE) = FALSE")
        scope_sql = " AND ".join(scope) if scope else "TRUE"
        code_clauses = [f"{col} = :code" for col in meta["code_cols"]]
        if meta["json_external_ids_col"]:
            ext = meta["json_external_ids_col"]
            code_clauses.extend(
                [
                    f"COALESCE({ext} ->> 'pms', '') = :code",
                    f"COALESCE({ext} ->> 'escapia', '') = :code",
                    f"COALESCE({ext} ->> 'airbnb', '') = :code",
                    f"COALESCE({ext} ->> 'vrbo', '') = :code",
                ]
            )
        if meta["json_extra_col"]:
            extra = meta["json_extra_col"]
            code_clauses.extend(
                [
                    f"COALESCE({extra} ->> 'external_id', '') = :code",
                    f"COALESCE({extra} ->> 'pms_external_id', '') = :code",
                    f"COALESCE({extra} ->> 'listing_id', '') = :code",
                ]
            )
        select_cols = [
            col
            for col in {
                canonical,
                meta["id_col"],
                meta["description_col"],
                meta["amenities_col"],
                meta["json_extra_col"],
                "property_code",
                "internal_code",
                "external_id",
                "property_external_id",
                "code",
                "property_name",
                "name",
                "address_street",
                "address_line1",
                "community",
                "bedrooms",
                "bathrooms",
                "sleeps",
                "max_occupancy",
                "wifi_network",
                "wifi_password",
                "parking_spaces",
                "parking_instructions",
                "check_in_time",
                "check_out_time",
                "has_pool",
                "pool_heated",
                "has_hot_tub",
                "pets_allowed",
                "property_policy_overrides",
            }
            if col and col in columns
        ]
        return (
            await self.session.execute(
                text(
                    f"""
                    SELECT {', '.join(select_cols)}
                    FROM properties
                    WHERE {scope_sql}
                      AND ({' OR '.join(code_clauses)})
                    LIMIT 1
                    """
                ),
                {"op": tenant, "code": property_code},
            )
        ).mappings().first()

    async def _load_profile_row(self, tenant: str, property_code: str) -> Optional[Dict[str, Any]]:
        if not property_code or not await self._table_columns("canonical_property_profiles"):
            return None
        return (
            await self.session.execute(
                text(
                    """
                    SELECT display_name, marketing_name, preferred_address, source, metadata
                    FROM canonical_property_profiles
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND canonical_property_code = :code
                    LIMIT 1
                    """
                ),
                {"tid": tenant, "code": property_code},
            )
        ).mappings().first()

    async def _load_pms_row(
        self,
        tenant: str,
        property_external_id: str,
        external_id: str,
        property_name: str,
    ) -> Optional[Dict[str, Any]]:
        meta = await self._pms_table_meta()
        if not meta["canonical_code_col"]:
            return None
        scope = []
        if meta["tenant_col"]:
            scope.append(f"{meta['tenant_col']}::text = :op")
        if "is_active" in meta["columns"]:
            scope.append("COALESCE(is_active, TRUE) = TRUE")
        scope_sql = " AND ".join(scope) if scope else "TRUE"
        code_values = [value for value in {property_external_id, external_id} if value]
        if code_values:
            row = (
                await self.session.execute(
                    text(
                        f"""
                        SELECT *
                        FROM pms_listings
                        WHERE {scope_sql}
                          AND {meta['canonical_code_col']} = ANY(:codes)
                        LIMIT 1
                        """
                    ),
                    {"op": tenant, "codes": code_values},
                )
            ).mappings().first()
            if row:
                return row
        if property_name and meta["name_col"]:
            return (
                await self.session.execute(
                    text(
                        f"""
                        SELECT *
                        FROM pms_listings
                        WHERE {scope_sql}
                          AND (
                            {self._ci_text_expr(meta['name_col'])} = LOWER(:name)
                            OR {self._ci_text_expr(meta['name_col'])} LIKE LOWER(:name_fuzzy)
                          )
                        LIMIT 1
                        """
                    ),
                    {"op": tenant, "name": property_name, "name_fuzzy": f"%{property_name[:20]}%"},
                )
            ).mappings().first()
        return None

    async def _load_concierge_knowledge(
        self,
        tenant_id: UUID,
        prop_row: Optional[Dict[str, Any]],
        property_external_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Load canonical scoped knowledge for the resolved property.

        Phase 4.2 makes the Brain read path canonical-only. If scoped
        knowledge is empty, callers see an empty concierge_knowledge block
        and decide how cautious to be; this seam no longer substitutes the
        legacy concierge_knowledge table.
        """
        property_id = prop_row.get("id") if prop_row else None
        if self.session is None or not property_id:
            return None

        effective = await get_scoped_knowledge_service().get_effective_knowledge_for_property(
            session=self.session,
            tenant_id=tenant_id,
            property_id=property_id,
        )
        if not (
            effective.effective_by_topic
            or effective.effective_freeform_faq
            or effective.all_entries_with_provenance
        ):
            return None

        projected = project_to_legacy_concierge_knowledge_shape(effective)
        return {
            "property_context": {},
            "facts": projected.get("facts") or {},
            "sections": projected.get("sections") or {},
            "faq": projected.get("faq") or [],
            "source": str(effective.retrieval_source or "unified"),
            "retrieval_source": str(effective.retrieval_source or "unified"),
        }

    async def _load_property_candidates(self, tenant: str, property_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        columns = property_meta["columns"]
        tenant_col = property_meta["tenant_col"]
        canonical_col = property_meta["canonical_code_col"]
        select_cols = []
        for col in {canonical_col, "external_id", "community", "address_street", "address_line1", *property_meta["name_cols"]}:
            if col and col in columns and col not in select_cols:
                select_cols.append(col)
        if not select_cols:
            return []
        where_parts = []
        if tenant_col:
            where_parts.append(f"{tenant_col}::text = :tid")
        if "deleted_at" in columns:
            where_parts.append("deleted_at IS NULL")
        if "is_deleted" in columns:
            where_parts.append("COALESCE(is_deleted, FALSE) = FALSE")
        rows = (
            await self.session.execute(
                text(
                    f"""
                    SELECT {', '.join(select_cols)}
                    FROM properties
                    WHERE {' AND '.join(where_parts) if where_parts else 'TRUE'}
                    """
                ),
                {"tid": tenant},
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def _load_ref_candidates(self, tenant: str) -> Dict[str, List[Dict[str, Any]]]:
        if not await self._table_columns("canonical_property_refs"):
            return {}
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT canonical_property_code, provider, ref_kind, ref_value
                    FROM canonical_property_refs
                    WHERE tenant_id = CAST(:tid AS uuid)
                    """
                ),
                {"tid": tenant},
            )
        ).mappings().all()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            code = str(row.get("canonical_property_code") or "").strip()
            if not code:
                continue
            grouped.setdefault(code, []).append(dict(row))
        return grouped

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

    async def _property_table_meta(self) -> dict:
        columns = await self._table_columns("properties")
        return {
            "columns": columns,
            "tenant_col": self._first_existing(columns, "tenant_id", "company_id"),
            "id_col": self._first_existing(columns, "property_id", "id"),
            "canonical_code_col": self._first_existing(columns, "property_code", "internal_code", "external_id", "property_external_id", "code"),
            "code_cols": [col for col in ("property_code", "internal_code", "external_id", "property_external_id", "code") if col in columns],
            "name_cols": [col for col in ("property_name", "name", "address_street", "address_line1", "community", "property_code", "external_id") if col in columns],
            "json_external_ids_col": self._first_existing(columns, "external_ids"),
            "json_extra_col": self._first_existing(columns, "extra_data"),
            "amenities_col": self._first_existing(columns, "amenities"),
            "description_col": self._first_existing(columns, "description", "general_notes"),
            "guide_url_col": self._first_existing(columns, "property_guide_url"),
        }

    async def _pms_table_meta(self) -> dict:
        columns = await self._table_columns("pms_listings")
        return {
            "columns": columns,
            "tenant_col": self._first_existing(columns, "company_id", "tenant_id"),
            "canonical_code_col": self._first_existing(columns, "external_id"),
            "name_col": self._first_existing(columns, "property_name", "name"),
            "listing_id_cols": [
                col
                for col in ("provider_listing_id", "listing_id", "external_id")
                if col in columns
            ],
            "unit_id_cols": [
                col
                for col in ("provider_unit_id", "unit_code", "unit_id", "property_code")
                if col in columns
            ],
        }

    @staticmethod
    def _dictish(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_value(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()

    @staticmethod
    def _website_path_variants(value: str) -> List[str]:
        raw = (value or "").strip()
        if not raw:
            return []
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc:
            raw = parsed.path or raw
        variants = [raw]
        if raw and not raw.startswith("/"):
            variants.append(f"/{raw}")
        deduped: List[str] = []
        seen = set()
        for variant in variants:
            normalized = variant.strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    @classmethod
    def _tokenize(cls, value: str) -> set[str]:
        return {token for token in cls._normalize_value(value).split() if token}

    @classmethod
    def _match_score(cls, query_norm: str, query_tokens: set[str], candidate: str) -> float:
        candidate_norm = cls._normalize_value(candidate)
        if not candidate_norm:
            return 0.0
        if candidate_norm == query_norm:
            return 1.0
        if query_norm and query_norm in candidate_norm:
            return 0.92
        if candidate_norm and candidate_norm in query_norm:
            return 0.88
        candidate_tokens = cls._tokenize(candidate)
        if not candidate_tokens or not query_tokens:
            return 0.0
        overlap = len(query_tokens & candidate_tokens)
        if not overlap:
            return 0.0
        coverage = overlap / max(len(query_tokens), 1)
        specificity = overlap / max(len(candidate_tokens), 1)
        return round((coverage * 0.7) + (specificity * 0.3), 4)


def get_canonical_property_service(session: AsyncSession) -> CanonicalPropertyService:
    return CanonicalPropertyService(session)
