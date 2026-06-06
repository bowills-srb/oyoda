"""
Property Import Service

Single authoritative path for writing property data into the `properties`
table (SQLAlchemy ORM) and then deriving vector-store embeddings from it.

Sources handled:
  1. MCP file scanner output  (onboarding — file upload path)
  2. PMS canonical listings   (onboarding — PMS path / ongoing sync)
  3. Website widget scrape    (onboarding — web-scraper path)

Design principles:
  - properties table is the single source of truth for every field
  - vector store (knowledge_embeddings) is always *derived* from DB rows,
    never written to in parallel with independent data
  - Upsert logic: match on (operator_id, internal_code) first,
    fall back to (operator_id, address_line1 fuzzy) so re-running never
    creates duplicates
  - All writes are idempotent — safe to call on every onboarding step
  - Non-fatal: errors are collected and returned, never raised
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.property_canonical_write_service import get_canonical_property_write_service

logger = logging.getLogger(__name__)


RAW_INGEST_SQL = """
CREATE TABLE IF NOT EXISTS property_ingest_events (
    ingest_event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    company_id UUID,
    market_id TEXT,
    source_type TEXT NOT NULL,
    source_label TEXT NOT NULL DEFAULT 'system',
    status TEXT NOT NULL DEFAULT 'completed',
    row_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    vector_indexed_count INTEGER NOT NULL DEFAULT 0,
    rows_with_unmapped_fields INTEGER NOT NULL DEFAULT 0,
    preserved_field_count INTEGER NOT NULL DEFAULT 0,
    observed_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    unmapped_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_property_ingest_events_tenant_created
    ON property_ingest_events (tenant_id, created_at DESC);
"""


BASE_FIELD_ALIASES: Dict[str, List[str]] = {
    "property_code": ["unit_code", "property_code", "code", "internal_code", "unit", "unitid"],
    "property_name": ["name", "property_name", "display_name", "marketing_name", "listing_name", "unit_name"],
    "property_id": ["property_id", "pms_property_id", "external_id"],
    "provider_name": ["provider", "provider_name", "pms_provider", "channel_manager", "source_provider"],
    "provider_account_id": ["provider_account_id", "account_id", "pmcid", "portfolio_id"],
    "provider_property_id": ["provider_property_id", "property_id", "pms_property_id", "external_id"],
    "provider_unit_id": ["provider_unit_id", "unit_code", "property_code", "unit", "unitid"],
    "provider_listing_id": ["provider_listing_id", "listing_id"],
    "provider_base_url": ["provider_base_url", "base_url"],
    "address1": ["address", "address1", "address_line1", "street", "address_street"],
    "address2": ["address2", "address_line2", "unit_number", "suite"],
    "city": ["city", "address_city"],
    "state": ["state", "province", "address_state"],
    "postal_code": ["postal_code", "zipcode", "zip", "address_zip"],
    "country": ["country"],
    "community": ["community", "neighborhood"],
    "has_pool": ["has_pool", "pool"],
    "has_hot_tub": ["has_hot_tub", "hot_tub"],
    "pets_allowed": ["pets_allowed", "pet_friendly"],
    "has_bikes": ["has_bikes", "bikes"],
    "wifi_network": ["wifi_network", "wifi_name", "wifi"],
    "wifi_password": ["wifi_password", "wifi_passcode"],
    "door_code": ["door_code", "door", "lock_code"],
    "gate_code": ["gate_code", "gate"],
    "check_in_time": ["check_in_time", "checkin_time"],
    "check_out_time": ["check_out_time", "checkout_time"],
    "airbnb_id": ["airbnb_id"],
    "vrbo_id": ["vrbo_id"],
    "booking_id": ["booking_id"],
    "expedia_id": ["expedia_id"],
    "property_type": ["property_type", "type"],
    "bedrooms": ["bedrooms", "beds"],
    "bathrooms": ["bathrooms", "baths"],
    "sleeps": ["sleeps", "max_occupancy", "occupancy"],
    "square_footage": ["square_footage", "sqft"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon"],
    "description": ["description", "notes", "general_notes"],
}

FIELD_MAPPING_PROFILE_OVERRIDES: Dict[str, Dict[str, List[str]]] = {
    "dashboard_upload": {},
    "owner_property_sheet": {
        "property_name": ["home_name", "house_name"],
        "address1": ["street_address", "property_address"],
        "community": ["subdivision", "community_name"],
        "description": ["owner_notes", "home_notes"],
    },
    "portfolio_reference": {
        "property_name": ["portfolio_name", "reference_name"],
        "property_code": ["portfolio_code", "reference_code"],
        "community": ["market_neighborhood"],
    },
    "escapia_export": {
        "property_id": ["id", "property_id"],
        "property_code": ["unit_code", "unit_code_display"],
    },
    "guesty_export": {
        "property_name": ["nickname", "title"],
        "property_id": ["_id", "listing_id"],
        "property_code": ["pms_unit_code", "internal_listing_code"],
        "address1": ["address_full", "full_address"],
    },
    "hostaway_export": {
        "property_name": ["listing_name", "internal_name"],
        "property_id": ["hostaway_id", "listing_map_id"],
        "property_code": ["custom_listing_name", "listing_shortcode"],
    },
}


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    operator_id: str
    inserted: int = 0
    updated: int = 0
    vector_indexed: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    property_ids: List[str] = field(default_factory=list)  # DB IDs of touched rows
    observed_columns: List[str] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)
    rows_with_unmapped_fields: int = 0
    preserved_field_count: int = 0
    ingest_event_id: Optional[str] = None
    mapping_profiles_used: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.inserted + self.updated

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PropertyImportService:
    """
    Upserts property rows and keeps the vector store in sync.

    Usage (from onboarding agent)::

        svc = PropertyImportService(db_session)

        # From MCP file scan
        result = await svc.import_from_file_scan(
            operator_id="op_beach_habitats",
            company_id="...",
            market_id="30a_fl",
            scan_result=session.policies["_file_scan_result"],
        )

        # From PMS connector
        from app.services.connectors.escapia_connector import EscapiaConnectorV2
        connector = EscapiaConnectorV2(company_id, creds)
        listings = await connector.fetch_listings()
        result = await svc.import_from_pms_listings(
            operator_id="op_beach_habitats",
            company_id="...",
            market_id="30a_fl",
            listings=listings,
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_ingest_ledger(self) -> None:
        await self.db.execute(text(RAW_INGEST_SQL))
        await self.db.commit()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def import_from_file_scan(
        self,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        scan_result: Dict[str, Any],
    ) -> ImportResult:
        """
        Import properties extracted by the MCP str-data-collector scanner.

        scan_result shape (from _run_mcp_file_scan):
          {
            "property_database": {
              "properties": [
                {
                  "code": "SEALAVIE",
                  "wifi_network": "...", "wifi_password": "...",
                  "door_code": "...", "gate_code": "...",
                  "check_in_time": "...", "check_out_time": "...",
                  "bedrooms": 4, "bathrooms": 3.0, "sleeps": 10,
                  "address": "123 Scenic Hwy 30A, Santa Rosa Beach FL",
                  ...
                },
                ...
              ]
            }
          }
        """
        result = ImportResult(operator_id=operator_id)
        props = (scan_result.get("property_database") or {}).get("properties", [])

        if not props:
            result.warnings.append("No properties in file scan result — nothing to import")
            result.ingest_event_id = await self._record_ingest_event(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                source_type="file_scan",
                source_label="file_scan_import",
                payload={"property_database": {"properties": props}},
                result=result,
            )
            return result

        for raw in props:
            try:
                record = self._file_scan_prop_to_record(raw, operator_id, company_id, market_id)
                db_id, action = await self._upsert_property(record)
                result.property_ids.append(db_id)
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1

                try:
                    await get_canonical_property_write_service(self.db).register_property_record(
                        UUID(str(company_id)),
                        canonical_property_code=str(record.get("internal_code") or record.get("name") or ""),
                        property_name=str(record.get("name") or ""),
                        address_line1=str(record.get("address_line1") or ""),
                        external_ids=record.get("external_ids") or {},
                        aliases=[
                            str(record.get("name") or ""),
                            str(record.get("address_line1") or ""),
                            str((record.get("extra_data") or {}).get("pms_external_id") or ""),
                        ],
                        source="file_scan_import",
                    )
                except Exception as exc:
                    logger.debug("[PropertyImport] canonical register skipped (file scan): %s", exc)

                # Derive vector doc from the canonical DB row
                indexed = await self._index_property_to_vector(operator_id, db_id, record)
                if indexed:
                    result.vector_indexed += 1

            except Exception as exc:
                msg = f"Failed to import property '{raw.get('code', '?')}': {exc}"
                logger.warning("[PropertyImport] %s", msg)
                result.errors.append(msg)

        logger.info(
            "[PropertyImport] file_scan → inserted=%d updated=%d vector=%d errors=%d",
            result.inserted, result.updated, result.vector_indexed, len(result.errors),
        )
        result.ingest_event_id = await self._record_ingest_event(
            operator_id=operator_id,
            company_id=company_id,
            market_id=market_id,
            source_type="file_scan",
            source_label="file_scan_import",
            payload={"property_database": {"properties": props}},
            result=result,
        )
        return result

    async def import_from_pms_listings(
        self,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        listings: List[Any],  # List[CanonicalListing]
    ) -> ImportResult:
        """
        Import properties from a PMS connector's fetch_listings() output.
        PMS data is authoritative — existing rows are overwritten for
        address/bedrooms/etc. but supplemental fields (WiFi/codes) are
        preserved if the PMS returns None.
        """
        result = ImportResult(operator_id=operator_id)

        for listing in listings:
            try:
                record = self._pms_listing_to_record(listing, operator_id, company_id, market_id)
                ref_pairs = record.pop("__canonical_ref_pairs", None)
                db_id, action = await self._upsert_property(record, pms_authoritative=True)
                result.property_ids.append(db_id)
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1

                try:
                    await get_canonical_property_write_service(self.db).register_property_record(
                        UUID(str(company_id)),
                        canonical_property_code=str(record.get("internal_code") or record.get("name") or ""),
                        property_name=str(record.get("name") or ""),
                        address_line1=str(record.get("address_line1") or ""),
                        external_ids=record.get("external_ids") or {},
                        aliases=[
                            str(record.get("name") or ""),
                            str(record.get("address_line1") or ""),
                            str((record.get("extra_data") or {}).get("pms_external_id") or ""),
                        ],
                        ref_pairs=ref_pairs,
                        source="pms_import",
                    )
                except Exception as exc:
                    logger.debug("[PropertyImport] canonical register skipped (pms): %s", exc)

                indexed = await self._index_property_to_vector(operator_id, db_id, record)
                if indexed:
                    result.vector_indexed += 1

            except Exception as exc:
                ext_id = getattr(listing, "external_id", "?")
                msg = f"Failed to import PMS listing '{ext_id}': {exc}"
                logger.warning("[PropertyImport] %s", msg)
                result.errors.append(msg)

        logger.info(
            "[PropertyImport] pms → inserted=%d updated=%d vector=%d errors=%d",
            result.inserted, result.updated, result.vector_indexed, len(result.errors),
        )
        result.ingest_event_id = await self._record_ingest_event(
            operator_id=operator_id,
            company_id=company_id,
            market_id=market_id,
            source_type="pms_sync",
            source_label="pms_import",
            payload={"listings": [self._serialize_listing_for_ledger(listing) for listing in listings]},
            result=result,
        )
        return result

    async def import_from_widget_scrape(
        self,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        scraped_properties: List[Dict[str, Any]],
    ) -> ImportResult:
        """
        Import properties scraped from an operator's public website.
        Widget data has lower authority than PMS — only fills empty fields.
        """
        result = ImportResult(operator_id=operator_id)

        for raw in scraped_properties:
            try:
                record = self._widget_prop_to_record(raw, operator_id, company_id, market_id)
                db_id, action = await self._upsert_property(record, pms_authoritative=False)
                result.property_ids.append(db_id)
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1

                try:
                    await get_canonical_property_write_service(self.db).register_property_record(
                        UUID(str(company_id)),
                        canonical_property_code=str(record.get("internal_code") or record.get("name") or ""),
                        property_name=str(record.get("name") or ""),
                        address_line1=str(record.get("address_line1") or ""),
                        external_ids=record.get("external_ids") or {},
                        aliases=[
                            str(record.get("name") or ""),
                            str(record.get("address_line1") or ""),
                        ],
                        source="widget_import",
                    )
                except Exception as exc:
                    logger.debug("[PropertyImport] canonical register skipped (widget): %s", exc)

                indexed = await self._index_property_to_vector(operator_id, db_id, record)
                if indexed:
                    result.vector_indexed += 1

            except Exception as exc:
                msg = f"Failed to import widget property '{raw.get('name', '?')}': {exc}"
                logger.warning("[PropertyImport] %s", msg)
                result.errors.append(msg)

        logger.info(
            "[PropertyImport] widget → inserted=%d updated=%d vector=%d errors=%d",
            result.inserted, result.updated, result.vector_indexed, len(result.errors),
        )
        result.ingest_event_id = await self._record_ingest_event(
            operator_id=operator_id,
            company_id=company_id,
            market_id=market_id,
            source_type="widget_scrape",
            source_label="widget_import",
            payload={"properties": scraped_properties},
            result=result,
        )
        return result

    async def import_from_tabular_rows(
        self,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        rows: List[Dict[str, Any]],
        *,
        source_label: str = "dashboard_upload",
    ) -> ImportResult:
        """
        Import a generic operator-uploaded property table.

        This is the stable path for future operator uploads from CSV/XLSX/JSON.
        We normalize mixed column names into the same canonical property record
        shape used elsewhere so uploads, PMS sync, and KB all feed the same DB.
        """
        result = ImportResult(operator_id=operator_id)
        custom_profiles = await self._load_custom_mapping_profiles(operator_id)
        if not rows:
            result.warnings.append("No rows found in uploaded file")
            result.ingest_event_id = await self._record_ingest_event(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                source_type="tabular_upload",
                source_label=source_label,
                payload={"rows": rows},
                result=result,
            )
            return result

        for idx, raw in enumerate(rows, start=1):
            try:
                record = self._tabular_prop_to_record(
                    raw,
                    operator_id,
                    company_id,
                    market_id,
                    source_label,
                    custom_profiles=custom_profiles,
                )
                diagnostics = record.pop("__import_diagnostics", {}) or {}
                ref_pairs = record.pop("__canonical_ref_pairs", None)
                observed = diagnostics.get("observed_columns") or []
                unmapped = diagnostics.get("unmapped_columns") or []
                preserved_count = int(diagnostics.get("preserved_field_count") or 0)
                mapping_profile = str(diagnostics.get("mapping_profile") or "").strip()
                result.observed_columns = sorted(set(result.observed_columns).union(observed))
                result.unmapped_columns = sorted(set(result.unmapped_columns).union(unmapped))
                if unmapped:
                    result.rows_with_unmapped_fields += 1
                result.preserved_field_count += preserved_count
                if mapping_profile and mapping_profile not in result.mapping_profiles_used:
                    result.mapping_profiles_used.append(mapping_profile)
                if not record.get("internal_code") and not record.get("address_line1"):
                    result.warnings.append(f"Skipped row {idx}: missing property code and address")
                    continue
                db_id, action = await self._upsert_property(record, pms_authoritative=False)
                result.property_ids.append(db_id)
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1

                try:
                    await get_canonical_property_write_service(self.db).register_property_record(
                        UUID(str(company_id)),
                        canonical_property_code=str(record.get("internal_code") or record.get("name") or ""),
                        display_name=str(record.get("name") or record.get("internal_code") or ""),
                        property_name=str(record.get("name") or ""),
                        address_line1=str(record.get("address_line1") or ""),
                        external_ids=record.get("external_ids") or {},
                        aliases=self._tabular_aliases(raw, record),
                        ref_pairs=ref_pairs,
                        source=source_label,
                    )
                except Exception as exc:
                    logger.debug("[PropertyImport] canonical register skipped (tabular): %s", exc)

                indexed = await self._index_property_to_vector(operator_id, db_id, record)
                if indexed:
                    result.vector_indexed += 1
            except Exception as exc:
                msg = f"Failed to import uploaded row {idx}: {exc}"
                logger.warning("[PropertyImport] %s", msg)
                result.errors.append(msg)

        logger.info(
            "[PropertyImport] %s → inserted=%d updated=%d vector=%d errors=%d unmapped_cols=%d rows_with_unmapped=%d",
            source_label,
            result.inserted,
            result.updated,
            result.vector_indexed,
            len(result.errors),
            len(result.unmapped_columns),
            result.rows_with_unmapped_fields,
        )
        result.ingest_event_id = await self._record_ingest_event(
            operator_id=operator_id,
            company_id=company_id,
            market_id=market_id,
            source_type="tabular_upload",
            source_label=source_label,
            payload={"rows": rows},
            result=result,
        )
        return result

    async def replay_ingest_event(
        self,
        *,
        ingest_event_id: str,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
    ) -> ImportResult:
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT source_type, source_label, payload
                    FROM property_ingest_events
                    WHERE ingest_event_id = CAST(:ingest_event_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"ingest_event_id": ingest_event_id, "tenant_id": operator_id},
            )
        ).mappings().first()
        if not row:
            raise ValueError("Ingest event not found")

        source_type = str(row.get("source_type") or "")
        source_label = str(row.get("source_label") or "dashboard_upload")
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        payload = payload if isinstance(payload, dict) else {}

        if source_type == "tabular_upload":
            return await self.import_from_tabular_rows(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                rows=payload.get("rows") or [],
                source_label=source_label,
            )
        if source_type == "widget_scrape":
            return await self.import_from_widget_scrape(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                scraped_properties=payload.get("properties") or [],
            )
        if source_type == "file_scan":
            return await self.import_from_file_scan(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                scan_result=payload,
            )
        if source_type == "pms_sync":
            listings = self._deserialize_listings_from_ledger(payload.get("listings") or [])
            return await self.import_from_pms_listings(
                operator_id=operator_id,
                company_id=company_id,
                market_id=market_id,
                listings=listings,
            )
        raise ValueError(f"Replay not supported for source type '{source_type}'")

    async def enrich_missing_fields(
        self,
        operator_id: str,
        company_id: str,
    ) -> Dict[str, Any]:
        """
        Scan the operator's properties table for incomplete rows and return
        a coverage report.  Called by the PROPERTIES onboarding step so the
        operator sees exactly what's missing before going live.

        Returns:
          {
            "total": int,
            "complete": int,              # all required + concierge fields present
            "missing_by_field": {
              "wifi_network": ["SEALAVIE", "SUNSEEKER"],
              "door_code": ["SUNSEEKER"],
              ...
            },
            "properties": [
              {"code": ..., "name": ..., "missing": [...fields...]},
              ...
            ]
          }
        """
        REQUIRED_FIELDS = ["address_line1", "bedrooms", "bathrooms"]
        CONCIERGE_FIELDS = ["wifi_network", "wifi_password", "door_code", "check_in_time", "check_out_time"]
        ALL_FIELDS = REQUIRED_FIELDS + CONCIERGE_FIELDS

        try:
            rows = await self.db.execute(
                text("""
                    SELECT internal_code, name, address_line1, bedrooms, bathrooms,
                           extra_data->>'wifi_network' AS wifi_network,
                           extra_data->>'wifi_password' AS wifi_password,
                           extra_data->>'door_code' AS door_code,
                           extra_data->>'check_in_time' AS check_in_time,
                           extra_data->>'check_out_time' AS check_out_time
                    FROM properties
                    WHERE tenant_id = :operator_id
                      AND deleted_at IS NULL
                    ORDER BY name
                """),
                {"operator_id": operator_id},
            )
            props = rows.mappings().all()
        except Exception as exc:
            logger.warning("[PropertyImport] enrich_missing_fields query failed: %s", exc)
            return {"total": 0, "complete": 0, "missing_by_field": {}, "properties": []}

        missing_by_field: Dict[str, List[str]] = {f: [] for f in ALL_FIELDS}
        prop_summaries = []
        complete_count = 0

        for p in props:
            code = p.get("internal_code") or p.get("name", "?")
            missing = []
            for f in ALL_FIELDS:
                val = p.get(f)
                if not val:
                    missing.append(f)
                    missing_by_field[f].append(code)
            prop_summaries.append({"code": code, "name": p.get("name", ""), "missing": missing})
            if not missing:
                complete_count += 1

        # Remove fields that are complete for everyone
        missing_by_field = {k: v for k, v in missing_by_field.items() if v}

        return {
            "total": len(props),
            "complete": complete_count,
            "missing_by_field": missing_by_field,
            "properties": prop_summaries,
        }

    # ------------------------------------------------------------------
    # Data shape converters
    # ------------------------------------------------------------------

    def _file_scan_prop_to_record(
        self,
        raw: Dict[str, Any],
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
    ) -> Dict[str, Any]:
        """Map MCP scanner output dict → flat DB record."""
        address = raw.get("address", "")
        city, state, postal = self._parse_address(address)

        # Parse bedrooms/bathrooms safely
        def _int(v): return int(v) if v is not None else None
        def _float(v): return float(v) if v is not None else None

        return {
            "tenant_id": operator_id,
            "company_id": company_id,
            "market_id": market_id,
            "internal_code": raw.get("code"),
            "name": raw.get("code") or raw.get("name") or "Unnamed Property",
            "status": "onboarding",
            "property_type": "single_family",
            "address_line1": address or "Address TBD",
            "city": city or "TBD",
            "state": state or "FL",
            "postal_code": postal or "",
            "country": "US",
            "bedrooms": _int(raw.get("bedrooms")) or 0,
            "bathrooms": _float(raw.get("bathrooms")) or 0.0,
            "sleeps": _int(raw.get("sleeps")),
            # Operational / concierge fields stored in extra_data JSONB
            "extra_data": {
                "wifi_network": raw.get("wifi_network"),
                "wifi_password": raw.get("wifi_password"),
                "door_code": raw.get("door_code"),
                "gate_code": raw.get("gate_code"),
                "check_in_time": raw.get("check_in_time", "4:00 PM"),
                "check_out_time": raw.get("check_out_time", "11:00 AM"),
                "source": "file_scan",
                "sources": raw.get("sources", []),
            },
        }

    def _pms_listing_to_record(
        self,
        listing: Any,  # CanonicalListing
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
    ) -> Dict[str, Any]:
        """Map CanonicalListing → flat DB record."""
        amenities_jsonb: Dict[str, Any] = {}
        if getattr(listing, "has_pool", False):
            amenities_jsonb["pool"] = {"type": "private", "heated": getattr(listing, "pool_heated", False)}
        if getattr(listing, "has_hot_tub", False):
            amenities_jsonb["hot_tub"] = True
        if getattr(listing, "has_waterfront", False):
            amenities_jsonb["beach_access"] = {"type": getattr(listing, "waterfront_type", "waterfront")}
        if getattr(listing, "pet_friendly", False):
            amenities_jsonb["pet_friendly"] = True
        if getattr(listing, "has_ev_charger", False):
            amenities_jsonb["ev_charger"] = True
        if getattr(listing, "has_game_room", False):
            amenities_jsonb["game_room"] = True

        extra: Dict[str, Any] = {
            "source": "pms",
            "pms_provider": str(getattr(listing, "pms_provider", "")),
            "pms_external_id": str(getattr(listing, "external_id", "")),
            "provider_account_id": str(getattr(listing, "provider_account_id", "") or "") or None,
            "provider_property_id": str(getattr(listing, "provider_property_id", "") or "") or None,
            "provider_unit_id": str(getattr(listing, "provider_unit_id", "") or "") or None,
            "provider_listing_id": str(getattr(listing, "provider_listing_id", "") or "") or None,
            "provider_base_url": str(getattr(listing, "provider_base_url", "") or "") or None,
        }
        for f in ("wifi_network", "wifi_password", "door_code", "gate_code",
                  "check_in_time", "check_out_time"):
            val = getattr(listing, f, None)
            if val is not None:
                extra[f] = val

        return {
            "tenant_id": operator_id,
            "company_id": company_id,
            "market_id": market_id,
            "internal_code": str(getattr(listing, "external_id", "")),
            "name": getattr(listing, "property_name", None) or getattr(listing, "address_line1", "Property"),
            "status": "active",
            "property_type": getattr(listing, "property_type", "single_family"),
            "address_line1": getattr(listing, "address_line1", ""),
            "address_line2": getattr(listing, "address_line2", None),
            "city": getattr(listing, "city", ""),
            "state": getattr(listing, "state", "FL"),
            "postal_code": getattr(listing, "postal_code", ""),
            "country": getattr(listing, "country", "US"),
            "latitude": getattr(listing, "latitude", None),
            "longitude": getattr(listing, "longitude", None),
            "bedrooms": getattr(listing, "bedrooms", 0),
            "bathrooms": float(getattr(listing, "bathrooms", 0)),
            "sleeps": getattr(listing, "sleeps", None),
            "square_footage": getattr(listing, "square_footage", None),
            "amenities": amenities_jsonb,
            "description": getattr(listing, "description", None),
            "extra_data": extra,
            # External ID tracking
            "external_ids": {
                str(getattr(listing, "pms_provider", "pms")): str(getattr(listing, "external_id", "")),
            },
            "__canonical_ref_pairs": self._provider_identity_ref_pairs(
                provider=str(getattr(listing, "pms_provider", "pms") or "pms"),
                provider_account_id=str(getattr(listing, "provider_account_id", "") or ""),
                provider_property_id=str(getattr(listing, "provider_property_id", "") or ""),
                provider_unit_id=str(getattr(listing, "provider_unit_id", "") or ""),
                provider_listing_id=str(getattr(listing, "provider_listing_id", "") or ""),
                metadata={
                    "source_table": "pms_listings",
                    "provider_base_url": str(getattr(listing, "provider_base_url", "") or ""),
                },
            ),
        }

    def _widget_prop_to_record(
        self,
        raw: Dict[str, Any],
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
    ) -> Dict[str, Any]:
        """Map website-widget scrape dict → flat DB record."""
        amenities_jsonb: Dict[str, Any] = {}
        raw_amenities = raw.get("amenities", [])
        if isinstance(raw_amenities, list):
            for a in raw_amenities:
                key = str(a).lower().replace(" ", "_")
                amenities_jsonb[key] = True

        address = raw.get("address", "")
        city, state, postal = self._parse_address(address)

        return {
            "tenant_id": operator_id,
            "company_id": company_id,
            "market_id": market_id,
            "internal_code": raw.get("property_code") or raw.get("code"),
            "name": raw.get("property_name") or raw.get("name") or "Unnamed Property",
            "status": "onboarding",
            "property_type": "single_family",
            "address_line1": address or "Address TBD",
            "city": city or raw.get("city", "TBD"),
            "state": state or raw.get("state", "FL"),
            "postal_code": postal or raw.get("postal_code", ""),
            "country": "US",
            "bedrooms": int(raw.get("bedrooms") or 0),
            "bathrooms": float(raw.get("bathrooms") or 0),
            "sleeps": raw.get("sleeps") or raw.get("max_occupancy"),
            "amenities": amenities_jsonb,
            "description": raw.get("description"),
            "photos": raw.get("photos", []),
            "extra_data": {
                "source": "website_widget",
                "listing_url": raw.get("url"),
            },
        }

    def _tabular_prop_to_record(
        self,
        raw: Dict[str, Any],
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        source_label: str,
        custom_profiles: Optional[Dict[str, Dict[str, List[str]]]] = None,
    ) -> Dict[str, Any]:
        normalized = {self._normalize_upload_key(k): v for k, v in (raw or {}).items()}
        empty_markers = (None, "", "nan", "None")
        mapping_profile = self._resolve_mapping_profile(normalized, source_label, custom_profiles=custom_profiles)
        field_aliases = self._field_aliases_for_profile(mapping_profile, custom_profiles=custom_profiles)

        def has_value(value: Any) -> bool:
            return value not in empty_markers

        def first(*keys: str):
            for key in keys:
                value = normalized.get(key)
                if has_value(value):
                    return value
            return None

        def pick(field_name: str):
            return first(*field_aliases.get(field_name, []))

        def as_int(value: Any) -> Optional[int]:
            if not has_value(value):
                return None
            try:
                return int(float(str(value).strip()))
            except Exception:
                return None

        def as_float(value: Any) -> Optional[float]:
            if not has_value(value):
                return None
            try:
                return float(str(value).strip())
            except Exception:
                return None

        def as_bool(value: Any) -> Optional[bool]:
            if not has_value(value):
                return None
            text_value = str(value).strip().lower()
            if text_value in {"true", "yes", "y", "1", "pool", "allowed"}:
                return True
            if text_value in {"false", "no", "n", "0", "none", "not allowed"}:
                return False
            return None

        property_code = str(pick("property_code") or "").strip()
        property_name = str(pick("property_name") or "").strip()
        property_id = str(pick("property_id") or "").strip()
        provider_name = str(pick("provider_name") or "pms").strip().lower() or "pms"
        provider_account_id = str(pick("provider_account_id") or "").strip()
        provider_property_id = str(pick("provider_property_id") or "").strip()
        provider_unit_id = str(pick("provider_unit_id") or "").strip()
        provider_listing_id = str(pick("provider_listing_id") or "").strip()
        provider_base_url = str(pick("provider_base_url") or "").strip()
        address1 = str(pick("address1") or "").strip()
        address2 = str(pick("address2") or "").strip()
        city = str(pick("city") or "").strip()
        state = str(pick("state") or "").strip()
        postal_code = str(pick("postal_code") or "").strip()
        country = str(pick("country") or "US").strip()
        community = str(pick("community") or "").strip()

        amenities_jsonb: Dict[str, Any] = {}
        if as_bool(pick("has_pool")):
            amenities_jsonb["pool"] = {"type": "private"}
        if as_bool(pick("has_hot_tub")):
            amenities_jsonb["hot_tub"] = True
        if as_bool(pick("pets_allowed")):
            amenities_jsonb["pet_friendly"] = True
        if as_bool(pick("has_bikes")):
            amenities_jsonb["bikes"] = True
        if community:
            amenities_jsonb["community"] = community

        extra_data = {
            "source": source_label,
            "provider_name": provider_name or None,
            "provider_account_id": provider_account_id or None,
            "provider_property_id": provider_property_id or None,
            "provider_unit_id": provider_unit_id or None,
            "provider_listing_id": provider_listing_id or None,
            "provider_base_url": provider_base_url or None,
            "mapping_profile": mapping_profile,
            "wifi_network": pick("wifi_network"),
            "wifi_password": pick("wifi_password"),
            "door_code": pick("door_code"),
            "gate_code": pick("gate_code"),
            "check_in_time": pick("check_in_time"),
            "check_out_time": pick("check_out_time"),
            "community": community or None,
            "source_columns": sorted([k for k, v in normalized.items() if v not in (None, "", "nan", "None")]),
        }
        external_ids = {}
        if property_id:
            external_ids["pms"] = property_id
        for provider_key, provider_name in (
            ("airbnb_id", "airbnb"),
            ("vrbo_id", "vrbo"),
            ("booking_id", "booking"),
            ("expedia_id", "expedia"),
        ):
            provider_value = pick(provider_key)
            if provider_value:
                external_ids[provider_name] = str(provider_value).strip()

        recognized_keys = {alias for aliases in field_aliases.values() for alias in aliases}
        non_empty_columns = sorted([k for k, v in normalized.items() if has_value(v)])
        unmapped_fields = {
            key: value
            for key, value in normalized.items()
            if has_value(value) and key not in recognized_keys
        }
        unmapped_columns = sorted(unmapped_fields.keys())

        return {
            "tenant_id": operator_id,
            "company_id": company_id,
            "market_id": market_id,
            "internal_code": property_code or property_id or property_name or address1,
            "name": property_name or property_code or address1 or "Unnamed Property",
            "status": "active",
            "property_type": str(pick("property_type") or "single_family"),
            "address_line1": address1 or "Address TBD",
            "address_line2": address2 or None,
            "city": city or "TBD",
            "state": state or "FL",
            "postal_code": postal_code,
            "country": country,
            "bedrooms": as_int(pick("bedrooms")) or 0,
            "bathrooms": as_float(pick("bathrooms")) or 0.0,
            "sleeps": as_int(pick("sleeps")),
            "square_footage": as_int(pick("square_footage")),
            "latitude": as_float(pick("latitude")),
            "longitude": as_float(pick("longitude")),
            "amenities": amenities_jsonb,
            "description": str(pick("description") or "") or None,
            "extra_data": {
                k: v for k, v in {
                    **extra_data,
                    "unmapped_fields": unmapped_fields or None,
                }.items() if v not in (None, "", [], {})
            },
            "external_ids": external_ids,
            "__canonical_ref_pairs": self._provider_identity_ref_pairs(
                provider=provider_name,
                provider_account_id=provider_account_id,
                provider_property_id=provider_property_id,
                provider_unit_id=provider_unit_id,
                provider_listing_id=provider_listing_id,
                metadata={
                    "source_label": source_label,
                    "provider_base_url": provider_base_url or None,
                },
            ),
            "__import_diagnostics": {
                "observed_columns": non_empty_columns,
                "unmapped_columns": unmapped_columns,
                "preserved_field_count": len(unmapped_fields),
                "mapping_profile": mapping_profile,
            },
        }

    def _provider_identity_ref_pairs(
        self,
        *,
        provider: str,
        provider_account_id: str = "",
        provider_property_id: str = "",
        provider_unit_id: str = "",
        provider_listing_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_provider = (provider or "pms").strip().lower() or "pms"
        base_metadata = dict(metadata or {})
        pairs: List[Dict[str, Any]] = []
        for ref_kind, ref_value, confidence in (
            ("provider_account_id", provider_account_id, 0.98),
            ("property_id", provider_property_id, 0.99),
            ("unit_id", provider_unit_id, 0.99),
            ("listing_id", provider_listing_id, 0.99),
        ):
            value = str(ref_value or "").strip()
            if not value:
                continue
            pairs.append(
                {
                    "provider": normalized_provider,
                    "ref_kind": ref_kind,
                    "ref_value": value,
                    "confidence": confidence,
                    "metadata": base_metadata,
                }
            )
        return pairs

    def _resolve_mapping_profile(
        self,
        normalized: Dict[str, Any],
        source_label: str,
        *,
        custom_profiles: Optional[Dict[str, Dict[str, List[str]]]] = None,
    ) -> str:
        available_profiles = set(FIELD_MAPPING_PROFILE_OVERRIDES.keys()) | set((custom_profiles or {}).keys())
        normalized_source = self._normalize_upload_key(source_label) or "dashboard_upload"
        if normalized_source in available_profiles:
            return normalized_source
        provider_hint = str(
            normalized.get("provider")
            or normalized.get("provider_name")
            or normalized.get("pms_provider")
            or normalized.get("channel_manager")
            or ""
        ).strip().lower()
        if provider_hint in available_profiles:
            return provider_hint
        provider_profile = f"{provider_hint}_export" if provider_hint else ""
        if provider_profile in available_profiles:
            return provider_profile
        return "dashboard_upload"

    def _field_aliases_for_profile(
        self,
        profile_name: str,
        *,
        custom_profiles: Optional[Dict[str, Dict[str, List[str]]]] = None,
    ) -> Dict[str, List[str]]:
        aliases = {field: list(keys) for field, keys in BASE_FIELD_ALIASES.items()}
        overrides = dict(FIELD_MAPPING_PROFILE_OVERRIDES.get(profile_name, {}))
        overrides.update((custom_profiles or {}).get(profile_name, {}))
        for field, extra_keys in overrides.items():
            merged = []
            for key in [*extra_keys, *aliases.get(field, [])]:
                normalized = self._normalize_upload_key(key)
                if normalized and normalized not in merged:
                    merged.append(normalized)
            aliases[field] = merged
        return aliases

    async def _load_custom_mapping_profiles(self, operator_id: str) -> Dict[str, Dict[str, List[str]]]:
        try:
            row = (
                await self.db.execute(
                    text(
                        """
                        SELECT extra
                        FROM operator_settings
                        WHERE tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": operator_id},
                )
            ).mappings().first()
        except Exception as exc:
            logger.debug("[PropertyImport] custom mapping profiles unavailable: %s", exc)
            return {}

        extra = row.get("extra") if row else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        extra = extra if isinstance(extra, dict) else {}
        raw_profiles = extra.get("property_import_profiles") or {}
        if not isinstance(raw_profiles, dict):
            return {}

        normalized_profiles: Dict[str, Dict[str, List[str]]] = {}
        for profile_name, field_map in raw_profiles.items():
            normalized_profile = self._normalize_upload_key(profile_name)
            if not normalized_profile or not isinstance(field_map, dict):
                continue
            profile_aliases: Dict[str, List[str]] = {}
            for field_name, aliases in field_map.items():
                normalized_field = self._normalize_upload_key(field_name)
                if not normalized_field:
                    continue
                values = aliases if isinstance(aliases, list) else [aliases]
                normalized_aliases = []
                for alias in values:
                    alias_value = self._normalize_upload_key(alias)
                    if alias_value and alias_value not in normalized_aliases:
                        normalized_aliases.append(alias_value)
                if normalized_aliases:
                    profile_aliases[normalized_field] = normalized_aliases
            if profile_aliases:
                normalized_profiles[normalized_profile] = profile_aliases
        return normalized_profiles

    def _tabular_aliases(self, raw: Dict[str, Any], record: Dict[str, Any]) -> List[str]:
        aliases = {
            str(record.get("name") or "").strip(),
            str(record.get("address_line1") or "").strip(),
            str((record.get("external_ids") or {}).get("pms") or "").strip(),
            str(record.get("internal_code") or "").strip(),
        }
        for key in ("name", "property_name", "marketing_name", "display_name", "unit_code", "property_id", "address", "address1"):
            value = raw.get(key) or raw.get(key.upper()) or raw.get(key.title())
            if value:
                aliases.add(str(value).strip())
        return [alias for alias in aliases if alias]

    @staticmethod
    def _normalize_upload_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    async def _record_ingest_event(
        self,
        *,
        operator_id: str,
        company_id: str,
        market_id: Optional[str],
        source_type: str,
        source_label: str,
        payload: Dict[str, Any],
        result: ImportResult,
    ) -> str:
        ingest_event_id = str(uuid4())
        try:
            await self.ensure_ingest_ledger()
            normalized_payload = self._coerce_jsonable(payload)
            summary = {
                "success": result.success,
                "total_rows_touched": result.total,
                "property_ids": list(result.property_ids),
            }
            await self.db.execute(
                text(
                    """
                    INSERT INTO property_ingest_events (
                        ingest_event_id, tenant_id, company_id, market_id,
                        source_type, source_label, status, row_count,
                        inserted_count, updated_count, vector_indexed_count,
                        rows_with_unmapped_fields, preserved_field_count,
                        observed_columns, unmapped_columns, warnings, errors,
                        payload, summary
                    ) VALUES (
                        CAST(:ingest_event_id AS uuid), CAST(:tenant_id AS uuid), CAST(:company_id AS uuid), :market_id,
                        :source_type, :source_label, :status, :row_count,
                        :inserted_count, :updated_count, :vector_indexed_count,
                        :rows_with_unmapped_fields, :preserved_field_count,
                        CAST(:observed_columns AS jsonb), CAST(:unmapped_columns AS jsonb), CAST(:warnings AS jsonb), CAST(:errors AS jsonb),
                        CAST(:payload AS jsonb), CAST(:summary AS jsonb)
                    )
                    """
                ),
                {
                    "ingest_event_id": ingest_event_id,
                    "tenant_id": operator_id,
                    "company_id": company_id,
                    "market_id": market_id,
                    "source_type": source_type,
                    "source_label": source_label,
                    "status": "completed" if result.success else "completed_with_errors",
                    "row_count": self._infer_payload_row_count(normalized_payload),
                    "inserted_count": result.inserted,
                    "updated_count": result.updated,
                    "vector_indexed_count": result.vector_indexed,
                    "rows_with_unmapped_fields": result.rows_with_unmapped_fields,
                    "preserved_field_count": result.preserved_field_count,
                    "observed_columns": json.dumps(result.observed_columns),
                    "unmapped_columns": json.dumps(result.unmapped_columns),
                    "warnings": json.dumps(result.warnings),
                    "errors": json.dumps(result.errors),
                    "payload": json.dumps(normalized_payload),
                    "summary": json.dumps(summary),
                },
            )
            await self.db.commit()
            return ingest_event_id
        except Exception as exc:
            logger.warning("[PropertyImport] ingest ledger write failed (non-fatal): %s", exc)
            return ""

    @staticmethod
    def _infer_payload_row_count(payload: Dict[str, Any]) -> int:
        for key in ("rows", "listings", "properties"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        property_database = payload.get("property_database")
        if isinstance(property_database, dict) and isinstance(property_database.get("properties"), list):
            return len(property_database["properties"])
        return 0

    @staticmethod
    def _coerce_jsonable(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): PropertyImportService._coerce_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [PropertyImportService._coerce_jsonable(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _serialize_listing_for_ledger(listing: Any) -> Dict[str, Any]:
        return {
            "external_id": str(getattr(listing, "external_id", "") or ""),
            "provider": str(getattr(listing, "pms_provider", "") or ""),
            "provider_account_id": str(getattr(listing, "provider_account_id", "") or ""),
            "provider_property_id": str(getattr(listing, "provider_property_id", "") or ""),
            "provider_unit_id": str(getattr(listing, "provider_unit_id", "") or ""),
            "provider_listing_id": str(getattr(listing, "provider_listing_id", "") or ""),
            "provider_base_url": str(getattr(listing, "provider_base_url", "") or ""),
            "property_name": str(getattr(listing, "property_name", "") or ""),
            "address_line1": str(getattr(listing, "address_line1", "") or ""),
            "city": str(getattr(listing, "city", "") or ""),
            "state": str(getattr(listing, "state", "") or ""),
            "postal_code": str(getattr(listing, "postal_code", "") or ""),
        }

    @staticmethod
    def _deserialize_listings_from_ledger(listings: List[Dict[str, Any]]) -> List[Any]:
        result: List[Any] = []
        for listing in listings or []:
            if isinstance(listing, dict):
                result.append(SimpleNamespace(**listing))
        return result

    # ------------------------------------------------------------------
    # DB upsert
    # ------------------------------------------------------------------

    async def _upsert_property(
        self,
        record: Dict[str, Any],
        pms_authoritative: bool = False,
    ) -> Tuple[str, str]:
        """
        Upsert a property row.

        Match strategy (in order):
          1. tenant_id + internal_code  (fastest, most reliable)
          2. tenant_id + address_line1  (fuzzy — normalised lower + strip)

        Returns (db_id, "inserted"|"updated").
        """
        import json

        operator_id = record["tenant_id"]
        internal_code = record.get("internal_code")
        address = (record.get("address_line1") or "").strip().lower()

        existing_id = None

        # Try code match first
        if internal_code:
            row = await self.db.execute(
                text("SELECT id FROM properties WHERE tenant_id=:t AND internal_code=:c AND deleted_at IS NULL LIMIT 1"),
                {"t": operator_id, "c": internal_code},
            )
            found = row.fetchone()
            if found:
                existing_id = str(found[0])

        # Fall back to address match
        if not existing_id and address and address != "address tbd":
            row = await self.db.execute(
                text("SELECT id FROM properties WHERE tenant_id=:t AND LOWER(TRIM(address_line1))=:a AND deleted_at IS NULL LIMIT 1"),
                {"t": operator_id, "a": address},
            )
            found = row.fetchone()
            if found:
                existing_id = str(found[0])

        extra_json = json.dumps(record.get("extra_data") or {})
        amenities_json = json.dumps(record.get("amenities") or {})
        external_ids_json = json.dumps(record.get("external_ids") or {})
        photos_json = json.dumps(record.get("photos") or [])

        if existing_id:
            if pms_authoritative:
                # PMS overwrites address/bedrooms/bathrooms/amenities
                await self.db.execute(
                    text("""
                        UPDATE properties SET
                            name            = COALESCE(:name, name),
                            address_line1   = COALESCE(:addr, address_line1),
                            city            = COALESCE(:city, city),
                            state           = COALESCE(:state, state),
                            postal_code     = COALESCE(:postal, postal_code),
                            latitude        = COALESCE(:lat, latitude),
                            longitude       = COALESCE(:lng, longitude),
                            bedrooms        = COALESCE(:beds, bedrooms),
                            bathrooms       = COALESCE(:baths, bathrooms),
                            sleeps          = COALESCE(:sleeps, sleeps),
                            square_footage  = COALESCE(:sqft, square_footage),
                            amenities       = amenities || CAST(:amenities AS jsonb),
                            description     = COALESCE(:desc, description),
                            external_ids    = external_ids || CAST(:ext_ids AS jsonb),
                            extra_data      = extra_data || CAST(:extra AS jsonb),
                            updated_at      = NOW()
                        WHERE id = :id
                    """),
                    {
                        "id": existing_id,
                        "name": record.get("name"),
                        "addr": record.get("address_line1"),
                        "city": record.get("city"),
                        "state": record.get("state"),
                        "postal": record.get("postal_code"),
                        "lat": record.get("latitude"),
                        "lng": record.get("longitude"),
                        "beds": record.get("bedrooms"),
                        "baths": record.get("bathrooms"),
                        "sleeps": record.get("sleeps"),
                        "sqft": record.get("square_footage"),
                        "amenities": amenities_json,
                        "desc": record.get("description"),
                        "ext_ids": external_ids_json,
                        "extra": extra_json,
                    },
                )
            else:
                # Non-authoritative: only fill NULL / empty fields
                await self.db.execute(
                    text("""
                        UPDATE properties SET
                            amenities  = amenities || CAST(:amenities AS jsonb),
                            extra_data = extra_data || CAST(:extra AS jsonb),
                            sleeps     = COALESCE(sleeps, :sleeps),
                            updated_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": existing_id, "amenities": amenities_json, "extra": extra_json, "sleeps": record.get("sleeps")},
                )
            await self.db.commit()
            return existing_id, "updated"

        else:
            # Insert new row
            new_id = str(uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO properties (
                        id, tenant_id, company_id, market_id,
                        internal_code, name, status, property_type,
                        address_line1, address_line2, city, state, postal_code, country,
                        latitude, longitude,
                        bedrooms, bathrooms, sleeps, square_footage,
                        amenities, external_ids, extra_data, photos, description,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :company_id, :market_id,
                        :internal_code, :name, :status, :property_type,
                        :address_line1, :address_line2, :city, :state, :postal_code, :country,
                        :latitude, :longitude,
                        :bedrooms, :bathrooms, :sleeps, :square_footage,
                        CAST(:amenities AS jsonb), CAST(:ext_ids AS jsonb),
                        CAST(:extra AS jsonb), CAST(:photos AS jsonb), :description,
                        NOW(), NOW()
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": new_id,
                    "tenant_id": operator_id,
                    "company_id": record.get("company_id", operator_id),
                    "market_id": record.get("market_id"),
                    "internal_code": internal_code,
                    "name": record.get("name", "Property"),
                    "status": record.get("status", "onboarding"),
                    "property_type": record.get("property_type", "single_family"),
                    "address_line1": record.get("address_line1", "Address TBD"),
                    "address_line2": record.get("address_line2"),
                    "city": record.get("city", "TBD"),
                    "state": record.get("state", "FL"),
                    "postal_code": record.get("postal_code", ""),
                    "country": record.get("country", "US"),
                    "latitude": record.get("latitude"),
                    "longitude": record.get("longitude"),
                    "bedrooms": record.get("bedrooms", 0),
                    "bathrooms": record.get("bathrooms", 0.0),
                    "sleeps": record.get("sleeps"),
                    "square_footage": record.get("square_footage"),
                    "amenities": amenities_json,
                    "ext_ids": external_ids_json,
                    "extra": extra_json,
                    "photos": photos_json,
                    "description": record.get("description"),
                },
            )
            await self.db.commit()
            return new_id, "inserted"

    # ------------------------------------------------------------------
    # Vector index (derived from canonical DB record)
    # ------------------------------------------------------------------

    async def _index_property_to_vector(
        self,
        operator_id: str,
        db_id: str,
        record: Dict[str, Any],
    ) -> bool:
        """
        Build a vector-store document from the canonical DB record.
        This is the ONLY place that writes property data to knowledge_embeddings.
        """
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()

            extra = record.get("extra_data") or {}
            amenities = record.get("amenities") or {}
            code = record.get("internal_code") or record.get("name", "")

            # Build the richest possible natural-language document
            lines = [f"Property: {record.get('name', code)} (code: {code})"]

            addr = record.get("address_line1", "")
            city = record.get("city", "")
            state = record.get("state", "")
            if addr and addr not in ("Address TBD",):
                lines.append(f"Address: {addr}, {city}, {state}")

            beds = record.get("bedrooms")
            baths = record.get("bathrooms")
            sleeps = record.get("sleeps")
            if beds:
                lines.append(f"Size: {beds} bedrooms, {baths} bathrooms" + (f", sleeps {sleeps}" if sleeps else ""))

            for field_key, label in [
                ("wifi_network",  "WiFi Network"),
                ("wifi_password", "WiFi Password"),
                ("door_code",     "Door Code"),
                ("gate_code",     "Gate Code"),
                ("check_in_time", "Check-In Time"),
                ("check_out_time","Check-Out Time"),
            ]:
                val = extra.get(field_key)
                if val:
                    lines.append(f"{label}: {val}")

            # Amenities
            amenity_labels = []
            if amenities.get("pool"):
                label = "heated pool" if (amenities["pool"] or {}).get("heated") else "pool"
                amenity_labels.append(label)
            for k, v in amenities.items():
                if k != "pool" and v:
                    amenity_labels.append(k.replace("_", " "))
            if amenity_labels:
                lines.append(f"Amenities: {', '.join(amenity_labels)}")

            if record.get("description"):
                lines.append(f"Description: {record['description'][:300]}")

            content = "\n".join(lines)

            result = await registry.call(
                "knowledge",
                "index_document",
                operator_id,
                {
                    "content": content,
                    "doc_type": "house_manual",
                    "property_code": code,
                    "source": "property_import",
                    "db_id": db_id,
                },
            )
            return result.success
        except Exception as exc:
            logger.warning("[PropertyImport] vector index failed for %s (non-fatal): %s", db_id, exc)
            return False

    # ------------------------------------------------------------------
    # Address helpers
    # ------------------------------------------------------------------

    def _parse_address(self, address: str) -> Tuple[str, str, str]:
        """
        Best-effort parse of 'Street, City, State Zip' into components.
        Returns (city, state, postal_code) — empty strings on failure.
        """
        if not address:
            return "", "", ""

        # Pattern: ends with 'ST 12345' or 'ST, 12345'
        m = re.search(
            r",\s*([A-Za-z\s]+),?\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$",
            address,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()

        # Pattern: 'City State' at end without zip
        m2 = re.search(r",\s*([A-Za-z\s]+),?\s*([A-Z]{2})\s*$", address)
        if m2:
            return m2.group(1).strip(), m2.group(2).strip(), ""

        return "", "", ""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

async def get_property_import_service(db: AsyncSession) -> PropertyImportService:
    return PropertyImportService(db)
