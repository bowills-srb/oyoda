from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY
from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
    ScopedKnowledgeEntry,
    ScopedKnowledgeService,
)
from app.services.knowledge.vector_store import Document, VectorStore
from app.services.observability.llm_usage_tracker import LLMCallTimer, LLMUsageTracker

logger = logging.getLogger(__name__)

TENANT_ID = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
OPERATION_TYPE = "phase_4_0_a_structured_backfill"
SERVICE_NAME = "phase_4_0_a_backfill"
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_PROVIDER = "anthropic"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_RETRIES = 4
ANTHROPIC_BACKOFF_INITIAL_SEC = 2.0
ANTHROPIC_BACKOFF_MAX_SEC = 30.0
ANTHROPIC_BACKOFF_JITTER = 0.5
PROPERTY_PROCESSING_DELAY_SEC = 0.5
VECTOR_QUERIES_BY_FIELD: dict[str, str] = {
    "bedrooms": "how many bedrooms does this property have",
    "bathrooms": "how many bathrooms does this property have",
    "max_occupancy": "maximum number of guests this property can accommodate sleeping arrangements",
    "pet_friendly": "are pets allowed at this property pet policy dogs",
    "has_hot_tub": "is there a hot tub or jacuzzi at this property",
    "has_waterfront": "is this property on the water waterfront beachfront gulf-front oceanfront",
    "beach_access_type": "how is the beach accessed from this property walking distance private beach",
    "wifi_network": "wifi network name SSID password internet",
    "parking_spaces": "how many parking spaces are available",
    "has_pool": "is there a pool at this property private pool community pool",
    "pool_heated": "can the pool be heated pool heating",
}

CANONICAL_TO_PROPERTY_COLUMNS: dict[str, tuple[str, ...]] = {
    "bedrooms": ("bedrooms",),
    "bathrooms": ("bathrooms",),
    "max_guests": ("sleeps", "max_occupancy"),
    "has_pool": ("has_pool",),
    "pool_heated": ("pool_heated",),
    "has_hot_tub": ("has_hot_tub",),
    "has_waterfront": ("has_waterfront",),
    "pet_friendly": ("pets_allowed",),
    "parking_summary": ("parking_instructions", "parking_spaces"),
    "beach_access_type": ("beach_access_type",),
    "community_name": ("community",),
    "description": ("general_notes",),
}

PROPERTY_GROUP_ENTRY_FIELDS = (
    "id",
    "property_code",
    "address_street",
    "community",
    "bedrooms",
    "bathrooms",
    "sleeps",
    "max_occupancy",
    "wifi_network",
    "parking_spaces",
    "parking_instructions",
    "has_pool",
    "pool_heated",
    "has_hot_tub",
    "pets_allowed",
    "check_in_time",
    "check_out_time",
    "general_notes",
    "phase_4_0_a_backfill_audit",
    "is_active",
)

BOOLEAN_FIELDS = {
    "has_pool",
    "pool_heated",
    "has_hot_tub",
    "has_waterfront",
    "pets_allowed",
}
# Fields where absence of evidence implies a False value. These are
# prominent amenities that would be mentioned in a property guidebook if
# present; long-tail amenities remain open-world.
CLOSED_WORLD_BOOLEAN_FIELDS: dict[str, str] = {
    "has_pool": "pool",
    "pool_heated": "pool heating",
    "has_hot_tub": "hot tub",
    "has_waterfront": "waterfront / beachfront / gulf-front access",
    "pet_friendly": "pet allowance",
}
NUMERIC_FIELDS = {"bedrooms", "bathrooms", "sleeps", "max_occupancy", "parking_spaces"}
TEXT_FIELDS = {"wifi_network", "parking_instructions", "community", "general_notes", "beach_access_type"}


@dataclass(frozen=True)
class FieldExtraction:
    values: dict[str, Any]
    audit: dict[str, Any]
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    failed: bool = False


@dataclass
class PropertyRunResult:
    property_code: str
    property_id: str
    fields_updated: list[str] = field(default_factory=list)
    fields_skipped: list[str] = field(default_factory=list)
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    tenant_id: str
    operation: str
    started_at: str
    completed_at: str = ""
    properties_processed: int = 0
    properties_updated: int = 0
    properties_skipped_already_complete: int = 0
    fields_populated_by_field: dict[str, dict[str, int]] = field(default_factory=dict)
    llm_calls_total: int = 0
    llm_cost_usd_total: float = 0.0
    errors: list[str] = field(default_factory=list)


class StructuredBackfillLLMClient:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        provider: str = DEFAULT_PROVIDER,
        api_key: Optional[str] = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.api_key = (api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")).strip()

    async def extract_json(
        self,
        *,
        property_id: UUID,
        property_code: str,
        field_name: str,
        source_entry_ids: Iterable[UUID],
        text_blob: str,
        prompt_hint: str,
        dry_run: bool,
    ) -> tuple[dict[str, Any], float, int]:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing for LLM fallback")

        system_prompt = (
            "You extract a single structured property field from short-term rental knowledge. "
            "Respond with ONLY a JSON object - no prose, no markdown fences, no preamble. "
            'Format: {"value": <extracted_value_or_null>, "confidence": "high|medium|low", '
            '"reasoning": "<one short sentence>"}. '
            "If the value is genuinely not in the provided knowledge, use null. "
            "If the value is in the knowledge but uncertain, return your best guess with confidence low."
        )
        user_prompt = (
            f"Property code: {property_code}\n"
            f"Field: {field_name}\n"
            f"Instruction: {prompt_hint}\n\n"
            f"Knowledge:\n{text_blob}\n"
        )
        timer = LLMCallTimer()

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await _post_with_retry(
                client=client,
                url=ANTHROPIC_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 250,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            payload = response.json()

        content_blocks = payload.get("content") or []
        raw_text = "".join(str(block.get("text") or "") for block in content_blocks if isinstance(block, dict))
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        parsed = _safe_json_loads(raw_text) or {}
        estimated_cost_usd = float(
            (
                await _record_llm_usage(
                    property_id=property_id,
                    property_code=property_code,
                    field_name=field_name,
                    source_entry_ids=list(source_entry_ids),
                    model=self.model,
                    provider=self.provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=timer.elapsed_ms(),
                    dry_run=dry_run,
                )
            )
        )
        return parsed, estimated_cost_usd, 1


class StructuredPropertyBackfillRunner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID = TENANT_ID,
        llm_client: Optional[StructuredBackfillLLMClient] = None,
        diagnose: bool = False,
        diagnose_properties: Optional[set[str]] = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.llm_client = llm_client or StructuredBackfillLLMClient()
        self.scoped_knowledge_service = ScopedKnowledgeService()
        self.diagnose = diagnose
        self.diagnose_properties = {item.strip() for item in (diagnose_properties or set()) if item.strip()}
        self._schema_cache: dict[str, set[str]] = {}
        self._target_columns: set[str] = set()
        self._property_id_col: str = "id"

    async def run(self, *, dry_run: bool) -> RunSummary:
        started_at = _utc_now_iso()
        properties = await self._load_target_properties()
        summary = RunSummary(
            tenant_id=str(self.tenant_id),
            operation=OPERATION_TYPE,
            started_at=started_at,
        )

        for property_row in properties:
            summary.properties_processed += 1
            result = await self._backfill_property(property_row, dry_run=dry_run, summary=summary)
            summary.llm_calls_total += result.llm_calls
            summary.llm_cost_usd_total += result.llm_cost_usd
            if result.errors:
                summary.errors.extend(result.errors)
            if result.fields_updated:
                summary.properties_updated += 1
            elif not result.errors:
                summary.properties_skipped_already_complete += 1
            await asyncio.sleep(_property_processing_delay_sec())

        summary.completed_at = _utc_now_iso()
        _write_report(summary)
        return summary

    async def _backfill_property(
        self,
        property_row: dict[str, Any],
        *,
        dry_run: bool,
        summary: RunSummary,
    ) -> PropertyRunResult:
        property_id = _coerce_uuid(property_row[self._property_id_col])
        property_code = str(property_row.get("property_code") or property_id)
        result = PropertyRunResult(property_code=property_code, property_id=str(property_id))
        audit = _as_dict(property_row.get("phase_4_0_a_backfill_audit"))

        effective = await self.scoped_knowledge_service.get_effective_knowledge_for_property(
            session=self.session,
            tenant_id=self.tenant_id,
            property_id=property_id,
        )
        freeform_entries = list(effective.effective_freeform_faq)
        topic_entries = effective.effective_by_topic
        property_diagnose: dict[str, Any] = {
            "property_id": str(property_id),
            "property_code": property_code,
            "topic_entries_found": sorted(topic_entries.keys()),
            "fields": {},
        }

        updates: dict[str, Any] = {}
        for field_name in self._candidate_fields():
            try:
                extraction = await self._extract_field(
                    field_name=field_name,
                    property_row=property_row,
                    topic_entries=topic_entries,
                    freeform_entries=freeform_entries,
                    dry_run=dry_run,
                    property_diagnose=property_diagnose,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[Phase4.0-A] extraction_failed property=%s field=%s error=%s",
                    property_code,
                    field_name,
                    exc,
                    exc_info=True,
                )
                result.errors.append(f"{field_name}: {type(exc).__name__}: {exc}")
                audit[field_name] = {
                    "value": None,
                    "source": "extraction_failed",
                    "error": str(exc),
                    "extracted_at": _utc_now_iso(),
                }
                self._increment_stats(summary, field_name, "failed")
                continue

            result.llm_calls += extraction.llm_calls
            result.llm_cost_usd += extraction.llm_cost_usd

            if not extraction.values:
                result.fields_skipped.append(field_name)
                continue

            field_updated = False
            for target_col, value in extraction.values.items():
                current_value = property_row.get(target_col)
                if self._should_write_column(target_col, current_value, audit):
                    updates[target_col] = value
                    field_updated = True
            audit[field_name] = extraction.audit
            if field_updated:
                result.fields_updated.append(field_name)
                self._increment_stats(summary, field_name, extraction.audit.get("source", "deterministic"))
            else:
                result.fields_skipped.append(field_name)

        if updates or audit != _as_dict(property_row.get("phase_4_0_a_backfill_audit")):
            updates["phase_4_0_a_backfill_audit"] = audit
            if not dry_run:
                await self._update_property_row(property_id, updates)

        if self.diagnose and (not self.diagnose_properties or property_code in self.diagnose_properties):
            self._write_diagnose_report(property_code, property_diagnose)

        return result

    async def _extract_field(
        self,
        *,
        field_name: str,
        property_row: dict[str, Any],
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        if field_name == "has_pool":
            return await self._extract_field_unified(
                field_name="has_pool",
                target_columns=("has_pool",),
                topic_ids=("pool_access",),
                deterministic_fn=_boolean_from_text,
                is_boolean=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "pool_heated":
            return await self._extract_field_unified(
                field_name="pool_heated",
                target_columns=("pool_heated",),
                topic_ids=("pool_heating_capability", "pool_access"),
                deterministic_fn=_boolean_from_text,
                is_boolean=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "has_hot_tub":
            return await self._extract_field_unified(
                field_name="has_hot_tub",
                target_columns=("has_hot_tub",),
                topic_ids=("hot_tub_access",),
                deterministic_fn=_boolean_from_text,
                is_boolean=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "has_waterfront":
            return await self._extract_field_unified(
                field_name="has_waterfront",
                target_columns=("has_waterfront",),
                topic_ids=("local_area", "beach_access"),
                deterministic_fn=_waterfront_from_text,
                is_boolean=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "pets_allowed":
            return await self._extract_field_unified(
                field_name="pet_friendly",
                target_columns=("pets_allowed",),
                topic_ids=("pet_policy", "pet_fee"),
                deterministic_fn=_pet_friendly_from_text,
                is_boolean=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "bedrooms":
            return await self._extract_field_unified(
                field_name="bedrooms",
                target_columns=("bedrooms",),
                topic_ids=("sleeping_arrangement",),
                deterministic_fn=None,
                regexes=(
                    re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),
                    re.compile(r"\b(\d+)\s*bed(?:room)?\b", re.IGNORECASE),
                ),
                is_numeric=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "bathrooms":
            return await self._extract_field_unified(
                field_name="bathrooms",
                target_columns=("bathrooms",),
                topic_ids=("sleeping_arrangement",),
                deterministic_fn=None,
                regexes=(
                    re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:bathrooms?|baths?|ba)\b", re.IGNORECASE),
                ),
                is_numeric=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "max_occupancy":
            return await self._extract_field_unified(
                field_name="max_occupancy",
                target_columns=("sleeps", "max_occupancy"),
                topic_ids=("max_occupancy", "sleeping_arrangement"),
                deterministic_fn=None,
                regexes=(
                    re.compile(r"\b(?:sleeps?|sleep up to|up to)\s*(\d+)\s*(?:guests?)?\b", re.IGNORECASE),
                    re.compile(r"\b(?:max(?:imum)?\s*(?:occupancy|guests?)|occupancy)\D{0,10}(\d+)\b", re.IGNORECASE),
                ),
                is_numeric=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "parking_spaces":
            return await self._extract_field_unified(
                field_name="parking_spaces",
                target_columns=("parking_spaces",),
                topic_ids=("parking",),
                deterministic_fn=None,
                regexes=(
                    re.compile(r"\b(?:parking for|space for|fits?)\s*(\d+)\s*(?:cars?|vehicles?)\b", re.IGNORECASE),
                    re.compile(r"\b(\d+)\s*(?:parking spaces?|cars?)\b", re.IGNORECASE),
                ),
                is_numeric=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "parking_instructions":
            return self._extract_parking_instructions(topic_entries)
        if field_name == "wifi_network":
            return await self._extract_field_unified(
                field_name="wifi_network",
                target_columns=("wifi_network",),
                topic_ids=("wifi_access",),
                deterministic_fn=_extract_wifi_network_from_text,
                is_text=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "beach_access_type":
            return await self._extract_field_unified(
                field_name="beach_access_type",
                target_columns=("beach_access_type",),
                topic_ids=("beach_access",),
                deterministic_fn=_beach_access_type_from_text,
                is_text=True,
                property_row=property_row,
                topic_entries=topic_entries,
                freeform_entries=freeform_entries,
                dry_run=dry_run,
                property_diagnose=property_diagnose,
            )
        if field_name == "community":
            return self._extract_community(property_row, topic_entries, freeform_entries)
        raise ValueError(f"unsupported field: {field_name}")

    def _extract_boolean_topic(
        self,
        topic_id: str,
        output_field: str,
        topic_entries: dict[str, ScopedKnowledgeEntry],
    ) -> FieldExtraction:
        entry = topic_entries.get(topic_id)
        if not entry:
            return FieldExtraction(values={}, audit={})
        answer = entry.answer_text
        value = _boolean_from_text(answer)
        if value is None:
            return FieldExtraction(values={}, audit={})
        return FieldExtraction(
            values={output_field: value},
            audit=_build_audit(
                value=value,
                source="topic_tag_boolean",
                source_entry_ids=[entry.knowledge_entry_id],
            ),
        )

    def _extract_pool_heated(self, topic_entries: dict[str, ScopedKnowledgeEntry]) -> FieldExtraction:
        entry = topic_entries.get("pool_heating_capability")
        if entry:
            heated = _boolean_from_text(entry.answer_text)
            if heated is not None:
                return FieldExtraction(
                    values={"has_pool": True, "pool_heated": heated},
                    audit=_build_audit(
                        value=heated,
                        source="topic_tag_boolean",
                        source_entry_ids=[entry.knowledge_entry_id],
                        extra={"paired_fields": {"has_pool": True}},
                    ),
                )
        pool_entry = topic_entries.get("pool_access")
        if pool_entry:
            has_pool = _boolean_from_text(pool_entry.answer_text)
            if has_pool is not None:
                return FieldExtraction(
                    values={"pool_heated": False, "has_pool": has_pool},
                    audit=_build_audit(
                        value=False,
                        source="topic_tag_negative_default",
                        source_entry_ids=[pool_entry.knowledge_entry_id],
                        extra={"paired_fields": {"has_pool": has_pool}},
                    ),
                )
        return FieldExtraction(values={}, audit={})

    async def _extract_waterfront(
        self,
        *,
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        candidates = []
        local_area = topic_entries.get("local_area")
        beach_access = topic_entries.get("beach_access")
        if local_area:
            candidates.append(local_area)
        if beach_access:
            candidates.append(beach_access)
        candidates.extend(entry for entry in freeform_entries if _looks_like_location_entry(entry))
        if not candidates:
            return FieldExtraction(values={}, audit={})
        combined = " ".join(entry.answer_text for entry in candidates)
        value = _waterfront_from_text(combined)
        if value is not None:
            self._record_diagnose_field(
                property_diagnose,
                "has_waterfront",
                matched_entries=candidates,
                llm_input=None,
                llm_response=None,
                final_decision={"value": value, "source": "text_match"},
            )
            return FieldExtraction(
                values={"has_waterfront": value},
                audit=_build_audit(
                    value=value,
                    source="text_match",
                    source_entry_ids=[entry.knowledge_entry_id for entry in candidates],
                ),
            )
        extraction = await self._extract_boolean_with_llm(
            output_field="has_waterfront",
            entries=candidates,
            property_id=property_id,
            property_code=property_code,
            prompt_hint="Is this property directly on the water or truly waterfront? Return true if yes, false if clearly not, null if unclear.",
            dry_run=dry_run,
            property_diagnose=property_diagnose,
        )
        if not extraction.values:
            self._record_diagnose_field(
                property_diagnose,
                "has_waterfront",
                matched_entries=candidates,
                llm_input=None,
                llm_response=None,
                final_decision={"value": None, "source": "unclear_no_write"},
            )
        return extraction

    async def _extract_pet_policy(
        self,
        *,
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        entry = topic_entries.get("pet_policy") or topic_entries.get("pet_fee")
        if entry:
            value = _pet_friendly_from_text(entry.answer_text)
            if value is not None:
                self._record_diagnose_field(
                    property_diagnose,
                    "pets_allowed",
                    matched_entries=[entry],
                    llm_input=None,
                    llm_response=None,
                    final_decision={"value": value, "source": "topic_tag_boolean_inverted"},
                )
                return FieldExtraction(
                    values={"pets_allowed": value},
                    audit=_build_audit(
                        value=value,
                        source="topic_tag_boolean_inverted",
                        source_entry_ids=[entry.knowledge_entry_id],
                    ),
                )

        relevant = _relevant_freeform_entries(freeform_entries, ("pet_policy", "pet_fee"))
        if not relevant:
            return FieldExtraction(values={}, audit={})

        combined = _combine_entry_text(relevant)
        deterministic = _pet_friendly_from_text(combined)
        if deterministic is not None:
            self._record_diagnose_field(
                property_diagnose,
                "pets_allowed",
                matched_entries=relevant,
                llm_input=None,
                llm_response=None,
                final_decision={"value": deterministic, "source": "freeform_text_match"},
            )
            return FieldExtraction(
                values={"pets_allowed": deterministic},
                audit=_build_audit(
                    value=deterministic,
                    source="freeform_text_match",
                    source_entry_ids=[entry.knowledge_entry_id for entry in relevant],
                ),
            )

        return await self._extract_boolean_with_llm(
            output_field="pets_allowed",
            entries=relevant,
            property_id=property_id,
            property_code=property_code,
            prompt_hint="Does this property allow pets? Return true if allowed, false if not allowed, null if unclear.",
            dry_run=dry_run,
            property_diagnose=property_diagnose,
        )

    async def _extract_numeric_with_llm(
        self,
        *,
        output_field: str,
        topic_ids: tuple[str, ...],
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        prompt_hint: str,
        regexes: tuple[re.Pattern[str], ...],
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        entries = [entry for topic_id in topic_ids if (entry := topic_entries.get(topic_id))]
        if not entries:
            entries = _relevant_freeform_entries(freeform_entries, topic_ids)
        if not entries:
            return FieldExtraction(values={}, audit={})

        extracted = _extract_first_numeric(entries, regexes)
        target_values = _numeric_output_map(output_field, extracted) if extracted is not None else {}
        if target_values:
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=entries,
                llm_input=None,
                llm_response=None,
                final_decision={"value": extracted, "source": "deterministic_regex"},
            )
            return FieldExtraction(
                values=target_values,
                audit=_build_audit(
                    value=extracted,
                    source="deterministic_regex",
                    source_entry_ids=[entry.knowledge_entry_id for entry in entries],
                ),
            )

        text_blob = _combine_entry_text(entries)
        parsed, cost_usd, llm_calls = await self.llm_client.extract_json(
            property_id=property_id,
            property_code=property_code,
            field_name=output_field,
            source_entry_ids=[entry.knowledge_entry_id for entry in entries if entry.knowledge_entry_id],
            text_blob=text_blob,
            prompt_hint=prompt_hint,
            dry_run=dry_run,
        )
        raw_value = parsed.get("value")
        if raw_value in (None, ""):
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=entries,
                llm_input=text_blob,
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_no_value"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        value = _coerce_numeric(raw_value)
        if value is None:
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=entries,
                llm_input=text_blob,
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_invalid_numeric"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        self._record_diagnose_field(
            property_diagnose,
            output_field,
            matched_entries=entries,
            llm_input=text_blob,
            llm_response=parsed,
            final_decision={"value": value, "source": "llm_extract"},
        )
        return FieldExtraction(
            values=_numeric_output_map(output_field, value),
            audit=_build_audit(
                value=value,
                source="llm_extract",
                source_entry_ids=[entry.knowledge_entry_id for entry in entries],
                extra={"model": self.llm_client.model, "confidence": parsed.get("confidence"), "reasoning": parsed.get("reasoning")},
            ),
            llm_calls=llm_calls,
            llm_cost_usd=cost_usd,
        )

    def _extract_parking_instructions(self, topic_entries: dict[str, ScopedKnowledgeEntry]) -> FieldExtraction:
        entry = topic_entries.get("parking")
        if not entry:
            return FieldExtraction(values={}, audit={})
        answer = entry.answer_text.strip()
        if not answer:
            return FieldExtraction(values={}, audit={})
        return FieldExtraction(
            values={"parking_instructions": answer},
            audit=_build_audit(
                value=answer,
                source="topic_tag_text",
                source_entry_ids=[entry.knowledge_entry_id],
            ),
        )

    async def _extract_wifi_network(
        self,
        *,
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        wifi_entries = [
            entry for entry in freeform_entries if "wifi" in entry.question_text.lower() or "wifi" in entry.answer_text.lower()
        ]
        if not wifi_entries:
            return FieldExtraction(values={}, audit={})
        deterministic = _extract_wifi_network_from_entries(wifi_entries)
        if deterministic:
            self._record_diagnose_field(
                property_diagnose,
                "wifi_network",
                matched_entries=wifi_entries,
                llm_input=None,
                llm_response=None,
                final_decision={"value": deterministic, "source": "deterministic_regex"},
            )
            return FieldExtraction(
                values={"wifi_network": deterministic},
                audit=_build_audit(
                    value=deterministic,
                    source="deterministic_regex",
                    source_entry_ids=[entry.knowledge_entry_id for entry in wifi_entries],
                ),
            )
        parsed, cost_usd, llm_calls = await self.llm_client.extract_json(
            property_id=property_id,
            property_code=property_code,
            field_name="wifi_network",
            source_entry_ids=[entry.knowledge_entry_id for entry in wifi_entries if entry.knowledge_entry_id],
            text_blob=_combine_entry_text(wifi_entries),
            prompt_hint="Extract only the WiFi network / SSID string. Do not return the password.",
            dry_run=dry_run,
        )
        value = str(parsed.get("value") or "").strip()
        if not value:
            self._record_diagnose_field(
                property_diagnose,
                "wifi_network",
                matched_entries=wifi_entries,
                llm_input=_combine_entry_text(wifi_entries),
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_no_value"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        self._record_diagnose_field(
            property_diagnose,
            "wifi_network",
            matched_entries=wifi_entries,
            llm_input=_combine_entry_text(wifi_entries),
            llm_response=parsed,
            final_decision={"value": value, "source": "llm_extract"},
        )
        return FieldExtraction(
            values={"wifi_network": value},
            audit=_build_audit(
                value=value,
                source="llm_extract",
                source_entry_ids=[entry.knowledge_entry_id for entry in wifi_entries],
                extra={"model": self.llm_client.model, "confidence": parsed.get("confidence"), "reasoning": parsed.get("reasoning")},
            ),
            llm_calls=llm_calls,
            llm_cost_usd=cost_usd,
        )

    async def _extract_beach_access_type(
        self,
        *,
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        entry = topic_entries.get("beach_access")
        relevant = [entry] if entry else _relevant_freeform_entries(freeform_entries, ("beach_access",))
        if not relevant:
            return FieldExtraction(values={}, audit={})
        combined = _combine_entry_text(relevant)
        value = _beach_access_type_from_text(combined)
        if value:
            self._record_diagnose_field(
                property_diagnose,
                "beach_access_type",
                matched_entries=relevant,
                llm_input=None,
                llm_response=None,
                final_decision={"value": value, "source": "deterministic_enum"},
            )
            return FieldExtraction(
                values={"beach_access_type": value},
                audit=_build_audit(
                    value=value,
                    source="deterministic_enum",
                    source_entry_ids=[entry.knowledge_entry_id for entry in relevant],
                ),
            )
        parsed, cost_usd, llm_calls = await self.llm_client.extract_json(
            property_id=property_id,
            property_code=property_code,
            field_name="beach_access_type",
            source_entry_ids=[entry.knowledge_entry_id for entry in relevant if entry.knowledge_entry_id],
            text_blob=combined,
            prompt_hint="Extract one enum for beach access type: private, walk_to, short_drive, public, nearby, or null if unclear.",
            dry_run=dry_run,
        )
        llm_value = str(parsed.get("value") or "").strip().lower()
        if llm_value not in {"private", "walk_to", "short_drive", "public", "nearby"}:
            self._record_diagnose_field(
                property_diagnose,
                "beach_access_type",
                matched_entries=relevant,
                llm_input=combined,
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_no_value"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        self._record_diagnose_field(
            property_diagnose,
            "beach_access_type",
            matched_entries=relevant,
            llm_input=combined,
            llm_response=parsed,
            final_decision={"value": llm_value, "source": "llm_extract"},
        )
        return FieldExtraction(
            values={"beach_access_type": llm_value},
            audit=_build_audit(
                value=llm_value,
                source="llm_extract",
                source_entry_ids=[entry.knowledge_entry_id for entry in relevant],
                extra={"model": self.llm_client.model, "confidence": parsed.get("confidence"), "reasoning": parsed.get("reasoning")},
            ),
            llm_calls=llm_calls,
            llm_cost_usd=cost_usd,
        )

    def _extract_community(
        self,
        property_row: dict[str, Any],
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
    ) -> FieldExtraction:
        current = str(property_row.get("community") or "").strip()
        if current:
            return FieldExtraction(
                values={},
                audit=_build_audit(value=current, source="pre_existing", source_entry_ids=[]),
            )
        candidates = []
        if topic_entries.get("local_area"):
            candidates.append(topic_entries["local_area"])
        candidates.extend(entry for entry in freeform_entries if _looks_like_location_entry(entry))
        combined = _combine_entry_text(candidates)
        if not combined:
            return FieldExtraction(values={}, audit={})
        value = _community_from_text(combined)
        if not value:
            return FieldExtraction(values={}, audit={})
        return FieldExtraction(
            values={"community": value},
            audit=_build_audit(
                value=value,
                source="deterministic_enum",
                source_entry_ids=[entry.knowledge_entry_id for entry in candidates],
            ),
        )

    def _candidate_fields(self) -> list[str]:
        fields = [
            "has_pool",
            "pool_heated",
            "has_hot_tub",
            "has_waterfront",
            "pets_allowed",
            "bedrooms",
            "bathrooms",
            "max_occupancy",
            "parking_spaces",
            "parking_instructions",
            "wifi_network",
            "beach_access_type",
            "community",
        ]
        available = []
        for field in fields:
            physical_cols = self._physical_columns_for_field(field)
            if any(col in self._target_columns for col in physical_cols):
                available.append(field)
        return available

    async def _retrieve_vector_chunks(
        self,
        *,
        property_code: str,
        query: str,
        top_k: int = 5,
        min_score: float = 0.25,
    ) -> list[Document]:
        try:
            store = VectorStore(self.session)
            result = await store.similarity_search(
                query=query,
                tenant_id=self.tenant_id,
                property_code=property_code,
                top_k=top_k,
                min_score=min_score,
            )
            return result.documents
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Phase4.0-A] vector_retrieval_failed property=%s query=%s error=%s",
                property_code,
                query[:60],
                exc,
            )
            return []

    async def _extract_field_unified(
        self,
        *,
        field_name: str,
        target_columns: tuple[str, ...],
        topic_ids: tuple[str, ...],
        deterministic_fn: Optional[Any],
        regexes: tuple[re.Pattern[str], ...] = (),
        is_boolean: bool = False,
        is_numeric: bool = False,
        is_text: bool = False,
        property_row: dict[str, Any],
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        property_id = _coerce_uuid(property_row[self._property_id_col])
        property_code = str(property_row.get("property_code") or "")
        vector_chunks: list[Document] = []
        parsed: Optional[dict[str, Any]] = None
        llm_calls = 0
        cost_usd = 0.0

        topic_text_sources = [entry for topic_id in topic_ids if (entry := topic_entries.get(topic_id)) and entry.answer_text]
        topic_combined = _combine_entry_text(topic_text_sources)

        if deterministic_fn and topic_combined:
            det_value = deterministic_fn(topic_combined)
            if det_value is not None and det_value != "":
                return self._build_tier_extraction(
                    field_name=field_name,
                    target_columns=target_columns,
                    value=det_value,
                    source="topic_tag_deterministic",
                    entries=topic_text_sources,
                    is_boolean=is_boolean,
                    is_numeric=is_numeric,
                    is_text=is_text,
                    property_diagnose=property_diagnose,
                )
        if regexes and topic_text_sources:
            num_value = _extract_first_numeric(topic_text_sources, regexes)
            if num_value is not None:
                return self._build_tier_extraction(
                    field_name=field_name,
                    target_columns=target_columns,
                    value=num_value,
                    source="topic_tag_regex",
                    entries=topic_text_sources,
                    is_boolean=is_boolean,
                    is_numeric=is_numeric,
                    is_text=is_text,
                    property_diagnose=property_diagnose,
                )

        relevant_freeform = _relevant_freeform_entries(freeform_entries, topic_ids)
        freeform_combined = _combine_entry_text(relevant_freeform)
        if deterministic_fn and freeform_combined:
            det_value = deterministic_fn(freeform_combined)
            if det_value is not None and det_value != "":
                return self._build_tier_extraction(
                    field_name=field_name,
                    target_columns=target_columns,
                    value=det_value,
                    source="freeform_keyword_deterministic",
                    entries=relevant_freeform,
                    is_boolean=is_boolean,
                    is_numeric=is_numeric,
                    is_text=is_text,
                    property_diagnose=property_diagnose,
                )
        if regexes and relevant_freeform:
            num_value = _extract_first_numeric(relevant_freeform, regexes)
            if num_value is not None:
                return self._build_tier_extraction(
                    field_name=field_name,
                    target_columns=target_columns,
                    value=num_value,
                    source="freeform_keyword_regex",
                    entries=relevant_freeform,
                    is_boolean=is_boolean,
                    is_numeric=is_numeric,
                    is_text=is_text,
                    property_diagnose=property_diagnose,
                )

        vector_query = VECTOR_QUERIES_BY_FIELD.get(field_name)
        if not vector_query:
            return FieldExtraction(values={}, audit={})
        try:
            vector_chunks = await self._retrieve_vector_chunks(property_code=property_code, query=vector_query, top_k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Phase4.0-A] vector_retrieval_failed property=%s field=%s error=%s",
                property_code,
                field_name,
                exc,
            )
            vector_chunks = []

        context_parts: list[str] = []
        chunk_doc_ids: list[str] = []
        for chunk in vector_chunks:
            context_parts.append(f"[chunk: {chunk.metadata.get('doc_type', 'general')}]\n{chunk.content}")
            if chunk.doc_id:
                chunk_doc_ids.append(str(chunk.doc_id))
        for entry in relevant_freeform:
            context_parts.append(f"Q: {entry.question_text}\nA: {entry.answer_text}")
        if not context_parts:
            if field_name in CLOSED_WORLD_BOOLEAN_FIELDS:
                evidence_summary = self._summarize_evidence_examined(
                    topic_text_sources=topic_text_sources,
                    relevant_freeform=relevant_freeform,
                    vector_chunks=vector_chunks,
                    llm_response=None,
                )
                self._record_diagnose_field(
                    property_diagnose,
                    field_name,
                    matched_entries=relevant_freeform,
                    llm_input=None,
                    llm_response=None,
                    final_decision={"value": False, "source": "closed_world_default"},
                    vector_chunks=vector_chunks,
                )
                return FieldExtraction(
                    values=self._field_to_target_columns(
                        field_name,
                        target_columns,
                        False,
                        is_boolean=True,
                        is_numeric=False,
                    ),
                    audit=_build_audit(
                        value=False,
                        source="closed_world_default",
                        source_entry_ids=[],
                        extra={
                            "amenity": CLOSED_WORLD_BOOLEAN_FIELDS[field_name],
                            "evidence_examined": evidence_summary,
                        },
                    ),
                )
            self._record_diagnose_field(
                property_diagnose,
                field_name,
                matched_entries=relevant_freeform,
                llm_input=None,
                llm_response=None,
                final_decision={"value": None, "source": "no_context"},
                vector_chunks=vector_chunks,
            )
            return FieldExtraction(values={}, audit={})

        text_blob = "\n\n".join(context_parts)[:8000]
        prompt_hint = self._prompt_hint_for_field(field_name, is_boolean=is_boolean, is_numeric=is_numeric, is_text=is_text)
        parsed, cost_usd, llm_calls = await self.llm_client.extract_json(
            property_id=property_id,
            property_code=property_code,
            field_name=field_name,
            source_entry_ids=[entry.knowledge_entry_id for entry in relevant_freeform if entry.knowledge_entry_id],
            text_blob=text_blob,
            prompt_hint=prompt_hint,
            dry_run=dry_run,
        )
        raw_value = parsed.get("value")
        value = self._coerce_field_value(field_name, raw_value, is_boolean=is_boolean, is_numeric=is_numeric, is_text=is_text)
        if value is None or value == "":
            if field_name in CLOSED_WORLD_BOOLEAN_FIELDS:
                evidence_summary = self._summarize_evidence_examined(
                    topic_text_sources=topic_text_sources,
                    relevant_freeform=relevant_freeform,
                    vector_chunks=vector_chunks,
                    llm_response=parsed,
                )
                logger.info(
                    "[Phase4.0-A] closed_world_default field=%s property_code=%s evidence=%s",
                    field_name,
                    property_code,
                    evidence_summary,
                )
                self._record_diagnose_field(
                    property_diagnose,
                    field_name,
                    matched_entries=relevant_freeform,
                    llm_input=text_blob,
                    llm_response=parsed,
                    final_decision={"value": False, "source": "closed_world_default"},
                    vector_chunks=vector_chunks,
                )
                return FieldExtraction(
                    values=self._field_to_target_columns(
                        field_name,
                        target_columns,
                        False,
                        is_boolean=True,
                        is_numeric=False,
                    ),
                    audit=_build_audit(
                        value=False,
                        source="closed_world_default",
                        source_entry_ids=[],
                        extra={
                            "amenity": CLOSED_WORLD_BOOLEAN_FIELDS[field_name],
                            "evidence_examined": evidence_summary,
                            "llm_response": parsed,
                        },
                    ),
                    llm_calls=llm_calls,
                    llm_cost_usd=cost_usd,
                )
            self._record_diagnose_field(
                property_diagnose,
                field_name,
                matched_entries=relevant_freeform,
                llm_input=text_blob,
                llm_response=parsed,
                final_decision={"value": None, "source": "vector_then_llm_no_value"},
                vector_chunks=vector_chunks,
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        self._record_diagnose_field(
            property_diagnose,
            field_name,
            matched_entries=relevant_freeform,
            llm_input=text_blob,
            llm_response=parsed,
            final_decision={"value": value, "source": "vector_then_llm"},
            vector_chunks=vector_chunks,
        )
        return FieldExtraction(
            values=self._field_to_target_columns(field_name, target_columns, value, is_boolean=is_boolean, is_numeric=is_numeric),
            audit=_build_audit(
                value=value,
                source="vector_then_llm",
                source_entry_ids=[entry.knowledge_entry_id for entry in relevant_freeform if entry.knowledge_entry_id],
                extra={
                    "model": self.llm_client.model,
                    "confidence": parsed.get("confidence"),
                    "reasoning": parsed.get("reasoning"),
                    "vector_chunks_used": chunk_doc_ids,
                },
            ),
            llm_calls=llm_calls,
            llm_cost_usd=cost_usd,
        )

    @staticmethod
    def _summarize_evidence_examined(
        *,
        topic_text_sources: list[ScopedKnowledgeEntry],
        relevant_freeform: list[ScopedKnowledgeEntry],
        vector_chunks: list[Document],
        llm_response: Optional[dict[str, Any]],
    ) -> str:
        parts = [
            f"topic_tagged_entries={len(topic_text_sources)}",
            f"freeform_keyword_matches={len(relevant_freeform)}",
            f"vector_chunks_retrieved={len(vector_chunks)}",
        ]
        if llm_response is not None:
            parts.append(f"llm_returned=null confidence={llm_response.get('confidence') or 'n/a'}")
        else:
            parts.append("llm_not_called")
        return " | ".join(parts)

    def _build_tier_extraction(
        self,
        *,
        field_name: str,
        target_columns: tuple[str, ...],
        value: Any,
        source: str,
        entries: list[ScopedKnowledgeEntry],
        is_boolean: bool,
        is_numeric: bool,
        is_text: bool,
        property_diagnose: Optional[dict[str, Any]],
    ) -> FieldExtraction:
        self._record_diagnose_field(
            property_diagnose,
            field_name,
            matched_entries=entries,
            llm_input=None,
            llm_response=None,
            final_decision={"value": value, "source": source},
            vector_chunks=[],
        )
        return FieldExtraction(
            values=self._field_to_target_columns(field_name, target_columns, value, is_boolean=is_boolean, is_numeric=is_numeric),
            audit=_build_audit(
                value=value,
                source=source,
                source_entry_ids=[entry.knowledge_entry_id for entry in entries if entry.knowledge_entry_id],
            ),
        )

    def _field_to_target_columns(
        self,
        field_name: str,
        target_columns: tuple[str, ...],
        value: Any,
        *,
        is_boolean: bool,
        is_numeric: bool,
    ) -> dict[str, Any]:
        if field_name == "max_occupancy":
            return {"sleeps": int(value), "max_occupancy": int(value)}
        if field_name == "pet_friendly":
            return {"pets_allowed": bool(value)}
        if field_name == "pool_heated":
            return {"pool_heated": bool(value), "has_pool": True}
        if field_name == "has_pool":
            return {"has_pool": bool(value)}
        return {col: value for col in target_columns}

    def _coerce_field_value(
        self,
        field_name: str,
        raw_value: Any,
        *,
        is_boolean: bool,
        is_numeric: bool,
        is_text: bool,
    ) -> Any:
        if raw_value in (None, ""):
            return None
        if is_boolean:
            return _coerce_boolean(raw_value)
        if is_numeric:
            return _coerce_numeric(raw_value)
        if is_text:
            value = str(raw_value).strip()
            return value or None
        return raw_value

    @staticmethod
    def _prompt_hint_for_field(field_name: str, *, is_boolean: bool, is_numeric: bool, is_text: bool) -> str:
        if is_boolean:
            return f"Does this property have or allow {field_name}? Return true if yes, false if no, null only if the knowledge does not address it."
        if is_numeric:
            return f"Extract the numeric value for {field_name}. Return as an integer or decimal."
        if is_text:
            return f"Extract the value for {field_name} as a short string."
        return f"Extract the value for {field_name}."

    async def _extract_boolean_with_fallback(
        self,
        *,
        topic_id: str,
        output_field: str,
        topic_entries: dict[str, ScopedKnowledgeEntry],
        freeform_entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        prompt_hint: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        entry = topic_entries.get(topic_id)
        if entry:
            value = _boolean_from_text(entry.answer_text)
            if value is not None:
                self._record_diagnose_field(
                    property_diagnose,
                    output_field,
                    matched_entries=[entry],
                    llm_input=None,
                    llm_response=None,
                    final_decision={"value": value, "source": "topic_tag_boolean"},
                )
                return FieldExtraction(
                    values={output_field: value},
                    audit=_build_audit(
                        value=value,
                        source="topic_tag_boolean",
                        source_entry_ids=[entry.knowledge_entry_id],
                    ),
                )

        relevant = _relevant_freeform_entries(freeform_entries, (topic_id,))
        if not relevant:
            return FieldExtraction(values={}, audit={})

        combined = _combine_entry_text(relevant)
        deterministic = _boolean_from_text(combined)
        if deterministic is not None:
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=relevant,
                llm_input=None,
                llm_response=None,
                final_decision={"value": deterministic, "source": "freeform_text_match"},
            )
            return FieldExtraction(
                values={output_field: deterministic},
                audit=_build_audit(
                    value=deterministic,
                    source="freeform_text_match",
                    source_entry_ids=[entry.knowledge_entry_id for entry in relevant],
                ),
            )

        return await self._extract_boolean_with_llm(
            output_field=output_field,
            entries=relevant,
            property_id=property_id,
            property_code=property_code,
            prompt_hint=prompt_hint,
            dry_run=dry_run,
            property_diagnose=property_diagnose,
        )

    async def _extract_boolean_with_llm(
        self,
        *,
        output_field: str,
        entries: list[ScopedKnowledgeEntry],
        property_id: UUID,
        property_code: str,
        prompt_hint: str,
        dry_run: bool,
        property_diagnose: Optional[dict[str, Any]] = None,
    ) -> FieldExtraction:
        text_blob = _combine_entry_text(entries)
        parsed, cost_usd, llm_calls = await self.llm_client.extract_json(
            property_id=property_id,
            property_code=property_code,
            field_name=output_field,
            source_entry_ids=[entry.knowledge_entry_id for entry in entries if entry.knowledge_entry_id],
            text_blob=text_blob,
            prompt_hint=prompt_hint,
            dry_run=dry_run,
        )
        raw_value = parsed.get("value")
        if raw_value is None or str(raw_value).strip() == "":
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=entries,
                llm_input=text_blob,
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_no_value"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        value = _coerce_boolean(raw_value)
        if value is None:
            self._record_diagnose_field(
                property_diagnose,
                output_field,
                matched_entries=entries,
                llm_input=text_blob,
                llm_response=parsed,
                final_decision={"value": None, "source": "llm_invalid_boolean"},
            )
            return FieldExtraction(values={}, audit={}, llm_calls=llm_calls, llm_cost_usd=cost_usd)
        self._record_diagnose_field(
            property_diagnose,
            output_field,
            matched_entries=entries,
            llm_input=text_blob,
            llm_response=parsed,
            final_decision={"value": value, "source": "llm_extract"},
        )
        return FieldExtraction(
            values={output_field: value},
            audit=_build_audit(
                value=value,
                source="llm_extract",
                source_entry_ids=[entry.knowledge_entry_id for entry in entries],
                extra={"model": self.llm_client.model, "confidence": parsed.get("confidence"), "reasoning": parsed.get("reasoning")},
            ),
            llm_calls=llm_calls,
            llm_cost_usd=cost_usd,
        )

    @staticmethod
    def _write_diagnose_report(property_code: str, payload: dict[str, Any]) -> None:
        report_dir = Path("tmp")
        report_dir.mkdir(exist_ok=True)
        path = report_dir / f"phase_4_0_a_diagnose_{property_code}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))

    @staticmethod
    def _record_diagnose_field(
        property_diagnose: Optional[dict[str, Any]],
        field_name: str,
        *,
        matched_entries: list[ScopedKnowledgeEntry],
        llm_input: Optional[str],
        llm_response: Optional[Any],
        final_decision: dict[str, Any],
        vector_chunks: Optional[list[Document]] = None,
    ) -> None:
        if property_diagnose is None:
            return
        property_diagnose.setdefault("fields", {})[field_name] = {
            "matched_entry_ids": [str(entry.knowledge_entry_id) for entry in matched_entries if entry.knowledge_entry_id],
            "matched_topics": [entry.topic_id for entry in matched_entries if entry.topic_id],
            "matched_freeform_sections": sorted(
                {
                    str((entry.metadata or {}).get("section_title") or "")
                    for entry in matched_entries
                    if (entry.metadata or {}).get("section_title")
                }
            ),
            "matched_text_preview": [_truncate_text(entry.answer_text, 200) for entry in matched_entries[:5]],
            "vector_chunks": [
                {
                    "doc_id": chunk.doc_id,
                    "doc_type": chunk.metadata.get("doc_type"),
                    "score": chunk.score,
                    "content_preview": _truncate_text(chunk.content, 200),
                }
                for chunk in (vector_chunks or [])
            ],
            "llm_input_preview": _truncate_text(llm_input, 200) if llm_input else None,
            "llm_response_preview": _truncate_text(json.dumps(llm_response, default=str), 200) if llm_response else None,
            "final_decision": final_decision,
        }

    def _physical_columns_for_field(self, field_name: str) -> tuple[str, ...]:
        if field_name == "community":
            return ("community",)
        if field_name == "max_occupancy":
            return ("sleeps", "max_occupancy")
        return CANONICAL_TO_PROPERTY_COLUMNS.get(field_name, (field_name,))

    async def _load_target_properties(self) -> list[dict[str, Any]]:
        columns = await self._table_columns("properties")
        self._target_columns = columns
        self._property_id_col = "id" if "id" in columns else "property_id"
        select_cols = [col for col in (self._property_id_col, *PROPERTY_GROUP_ENTRY_FIELDS) if col in columns]
        rows = (
            await self.session.execute(
                text(
                    f"""
                    SELECT {", ".join(select_cols)}
                    FROM properties
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND COALESCE(is_active, TRUE) = TRUE
                    ORDER BY property_code
                    """
                ),
                {"tenant_id": str(self.tenant_id)},
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def _update_property_row(self, property_id: UUID, updates: dict[str, Any]) -> None:
        assignments = []
        params: dict[str, Any] = {"property_id": str(property_id)}
        for idx, (column, value) in enumerate(updates.items()):
            param = f"value_{idx}"
            if column == "phase_4_0_a_backfill_audit":
                assignments.append(f"{column} = CAST(:{param} AS jsonb)")
                params[param] = json.dumps(value, default=str)
            else:
                assignments.append(f"{column} = :{param}")
                params[param] = value
        await self.session.execute(
            text(
                f"""
                UPDATE properties
                SET {", ".join(assignments)},
                    updated_at = NOW()
                WHERE {self._property_id_col} = CAST(:property_id AS uuid)
                """
            ),
            params,
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

    def _should_write_column(self, column: str, current_value: Any, audit: dict[str, Any]) -> bool:
        if column in BOOLEAN_FIELDS:
            return column not in audit
        if column in NUMERIC_FIELDS:
            return current_value in (None, 0, 0.0, "0", "")
        if column in TEXT_FIELDS:
            return str(current_value or "").strip() == ""
        return current_value in (None, "")

    @staticmethod
    def _increment_stats(summary: RunSummary, field_name: str, source: str) -> None:
        bucket = summary.fields_populated_by_field.setdefault(
            field_name,
            {"populated": 0, "deterministic": 0, "llm": 0, "failed": 0},
        )
        bucket["populated"] += 1
        if source.startswith("llm"):
            bucket["llm"] += 1
        elif source == "failed":
            bucket["failed"] += 1
        else:
            bucket["deterministic"] += 1


async def _record_llm_usage(
    *,
    property_id: UUID,
    property_code: str,
    field_name: str,
    source_entry_ids: list[UUID],
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    dry_run: bool,
) -> Any:
    from app.services.observability.model_pricing import calculate_cost

    cost = calculate_cost(model, input_tokens, output_tokens)
    if not dry_run:
        await LLMUsageTracker.record(
            service_name=SERVICE_NAME,
            tenant_id=TENANT_ID,
            request_type=OPERATION_TYPE,
            provider=provider,
            model_id=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=True,
            latency_ms=latency_ms,
            metadata={
                "property_id": str(property_id),
                "property_code": property_code,
                "field_name": field_name,
                "source_entry_ids": [str(item) for item in source_entry_ids],
            },
        )
    return cost


def _build_audit(
    *,
    value: Any,
    source: str,
    source_entry_ids: Iterable[Optional[UUID]],
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = {
        "value": value,
        "source": source,
        "source_entry_ids": [str(item) for item in source_entry_ids if item],
        "extracted_at": _utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    return payload


def _boolean_from_text(value: str) -> Optional[bool]:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return None
    positive = ("yes", "available", "included", "has a", "private pool", "heated pool", "hot tub", "pool")
    negative = ("no ", "no.", "not available", "does not have", "without", "no pool", "no hot tub", "not heated")
    if "shared community pool" in lowered or "community pool" in lowered:
        return True
    if any(token in lowered for token in negative):
        return False
    if any(token in lowered for token in positive):
        return True
    return None


def _pet_friendly_from_text(value: str) -> Optional[bool]:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return None
    if any(token in lowered for token in ("no pets", "pets are not allowed", "pets not allowed", "not pet friendly")):
        return False
    if any(token in lowered for token in ("pets allowed", "pet friendly", "pets welcome", "dogs allowed")):
        return True
    return None


def _waterfront_from_text(value: str) -> Optional[bool]:
    lowered = str(value or "").lower()
    positive = (
        "waterfront",
        "beachfront",
        "oceanfront",
        "gulf front",
        "gulf-front",
        "on the water",
        "bayfront",
        "lakefront",
        "riverfront",
        "directly on the beach",
        "steps to the beach",
        "directly on the gulf",
        "on the gulf",
        "on the bay",
        "on the lake",
    )
    negative = (
        "short drive to beach",
        "drive to the beach",
        "short walk to beach",
        "walk to beach",
        "minutes to the beach",
    )
    if any(token in lowered for token in positive):
        return True
    if any(token in lowered for token in negative):
        return False
    return None


def _extract_first_numeric(entries: list[ScopedKnowledgeEntry], regexes: tuple[re.Pattern[str], ...]) -> Optional[float]:
    for entry in entries:
        answer = entry.answer_text
        for regex in regexes:
            match = regex.search(answer)
            if match:
                raw_value = match.group(1)
                return _coerce_numeric(raw_value)
    return None


def _coerce_numeric(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except Exception:
        return None
    if number.is_integer():
        return int(number)
    return round(number, 1)


def _numeric_output_map(output_field: str, value: float | int) -> dict[str, Any]:
    if output_field == "max_occupancy":
        return {"sleeps": int(value), "max_occupancy": int(value)}
    if output_field == "bathrooms":
        return {"bathrooms": value}
    return {output_field: int(value) if float(value).is_integer() else value}


def _extract_wifi_network_from_entries(entries: list[ScopedKnowledgeEntry]) -> Optional[str]:
    patterns = (
        re.compile(r"(?:wifi|wi-fi)(?:\s+network|\s+name)?\s*[:\-]\s*([A-Za-z0-9 _.-]{3,})", re.IGNORECASE),
        re.compile(r"(?:network|ssid)\s*(?:name)?\s*[:\-]\s*([A-Za-z0-9 _.-]{3,})", re.IGNORECASE),
        re.compile(r"connect to\s+([A-Za-z0-9 _.-]{3,})\s*(?:with|using|password)", re.IGNORECASE),
    )
    for entry in entries:
        text_value = f"{entry.question_text}\n{entry.answer_text}"
        for pattern in patterns:
            match = pattern.search(text_value)
            if match:
                candidate = re.split(r"\bpassword\b|\n|[.](?:\s|$)", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
                candidate = candidate.strip().strip(".:,;")
                if candidate and "password" not in candidate.lower():
                    return candidate
    return None


def _extract_wifi_network_from_text(value: str) -> Optional[str]:
    pseudo_entry = ScopedKnowledgeEntry(
        knowledge_entry_id=None,
        tenant_id=TENANT_ID,
        scope_type="property",
        scope_target_id=TENANT_ID,
        topic_id=None,
        question_text="wifi",
        question_key="wifi",
        answer_text=str(value or ""),
        tags=[],
        source="derived",
        metadata={},
        created_by_user_id=None,
        version=1,
    )
    return _extract_wifi_network_from_entries([pseudo_entry])


def _beach_access_type_from_text(value: str) -> str:
    lowered = str(value or "").lower()
    if "private beach" in lowered or "private access" in lowered:
        return "private"
    if (
        "walk to beach" in lowered
        or "walk to the beach" in lowered
        or "short walk" in lowered
        or "steps to the beach" in lowered
        or "walkover" in lowered
        or "minutes walk" in lowered
    ):
        return "walk_to"
    if "drive to the beach" in lowered or "short drive" in lowered:
        return "short_drive"
    if "public access" in lowered or "public beach" in lowered:
        return "public"
    if "beach" in lowered:
        return "nearby"
    return ""


def _community_from_text(value: str) -> str:
    lowered = str(value or "").lower()
    communities = {
        "watercolor": ("watercolor", "water color"),
        "rosemary_beach": ("rosemary beach",),
        "alys_beach": ("alys beach",),
        "seaside": ("seaside",),
        "grayton_beach": ("grayton beach",),
        "blue_mountain": ("blue mountain",),
        "seagrove": ("seagrove",),
        "watersound": ("watersound", "water sound"),
        "seacrest": ("seacrest",),
        "inlet_beach": ("inlet beach",),
    }
    for canonical, labels in communities.items():
        if any(label in lowered for label in labels):
            return canonical
    return ""


def _combine_entry_text(entries: list[ScopedKnowledgeEntry]) -> str:
    return "\n\n".join(
        f"Question: {entry.question_text}\nAnswer: {entry.answer_text}" for entry in entries if entry.answer_text
    )


def _relevant_freeform_entries(
    entries: list[ScopedKnowledgeEntry],
    topic_ids: tuple[str, ...],
) -> list[ScopedKnowledgeEntry]:
    keywords = set()
    for topic_id in topic_ids:
        topic = TOPIC_REGISTRY.get(topic_id)
        if topic:
            keywords.update(item.lower() for item in topic.classifier_keywords)
    matched = []
    for entry in entries:
        haystack = f"{entry.question_text} {entry.answer_text}".lower()
        if any(keyword in haystack for keyword in keywords):
            matched.append(entry)
    return matched


def _looks_like_location_entry(entry: ScopedKnowledgeEntry) -> bool:
    metadata = entry.metadata or {}
    section_title = str(metadata.get("section_title") or "").lower()
    return section_title in {"about property", "travel tips", "recommendations"} or "local" in entry.question_text.lower()


def _safe_json_loads(value: str) -> Optional[dict[str, Any]]:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
    try:
        loaded = json.loads(cleaned)
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


async def _post_with_retry(client: httpx.AsyncClient, **kwargs: Any) -> httpx.Response:
    """POST to Anthropic with 429-aware exponential backoff."""
    attempt = 0
    last_exc: Optional[Exception] = None
    while attempt < ANTHROPIC_MAX_RETRIES:
        try:
            response = await client.post(**kwargs)
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        wait_sec = float(retry_after)
                    except (TypeError, ValueError):
                        wait_sec = min(
                            ANTHROPIC_BACKOFF_INITIAL_SEC * (2 ** attempt),
                            ANTHROPIC_BACKOFF_MAX_SEC,
                        )
                else:
                    wait_sec = min(
                        ANTHROPIC_BACKOFF_INITIAL_SEC * (2 ** attempt),
                        ANTHROPIC_BACKOFF_MAX_SEC,
                    )
                wait_sec += random.uniform(0, ANTHROPIC_BACKOFF_JITTER)
                logger.warning("[Phase4.0-A] anthropic_429 attempt=%s wait_sec=%.1f", attempt + 1, wait_sec)
                await asyncio.sleep(wait_sec)
                attempt += 1
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                last_exc = exc
                attempt += 1
                continue
            raise
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= 1:
                raise
            wait_sec = ANTHROPIC_BACKOFF_INITIAL_SEC + random.uniform(0, ANTHROPIC_BACKOFF_JITTER)
            logger.warning("[Phase4.0-A] anthropic_request_error retry wait_sec=%.1f", wait_sec)
            await asyncio.sleep(wait_sec)
            attempt += 1
    raise RuntimeError(f"Anthropic API exhausted retries ({ANTHROPIC_MAX_RETRIES}) - last error: {last_exc}")


def _property_processing_delay_sec() -> float:
    raw_value = os.getenv("PHASE_4_0_A_PROPERTY_DELAY_SEC", str(PROPERTY_PROCESSING_DELAY_SEC)).strip()
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return PROPERTY_PROCESSING_DELAY_SEC
    return max(0.0, value)


def _coerce_boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    lowered = str(value or "").strip().lower()
    if lowered in {"true", "yes", "y", "1"}:
        return True
    if lowered in {"false", "no", "n", "0"}:
        return False
    return None


def _truncate_text(value: Optional[str], max_len: int) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value)
    if len(text_value) <= max_len:
        return text_value
    return f"{text_value[:max_len]}..."


def _coerce_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _write_report(summary: RunSummary) -> None:
    report_dir = Path("tmp")
    report_dir.mkdir(exist_ok=True)
    started_slug = re.sub(r"[^0-9T]", "", summary.started_at.replace(":", "").replace("-", ""))[:15]
    report_path = report_dir / f"phase_4_0_a_backfill_report_{started_slug}.json"
    report_path.write_text(json.dumps(asdict(summary), indent=2, default=str))
    logger.info("[Phase4.0-A] wrote_report path=%s", report_path)


async def run_backfill(
    *,
    dry_run: bool,
    diagnose: bool = False,
    diagnose_properties: Optional[list[str]] = None,
) -> RunSummary:
    async with get_db_session() as session:
        runner = StructuredPropertyBackfillRunner(
            session,
            diagnose=diagnose,
            diagnose_properties=set(diagnose_properties or []),
        )
        summary = await runner.run(dry_run=dry_run)
        return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 4.0-A structured properties backfill")
    parser.add_argument("--dry-run", action="store_true", help="Compute updates without writing properties or llm usage events")
    parser.add_argument("--diagnose", action="store_true", help="Write per-property extraction diagnostics to tmp/")
    parser.add_argument("--diagnose-properties", nargs="+", default=[], help="Limit diagnose output to specific property_codes")
    return parser


async def _async_main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = await run_backfill(
        dry_run=bool(args.dry_run),
        diagnose=bool(args.diagnose),
        diagnose_properties=list(args.diagnose_properties or []),
    )
    print(json.dumps(asdict(summary), indent=2, default=str))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import asyncio

    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
