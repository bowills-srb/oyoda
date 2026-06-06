"""
operator_app.py — Oyvoda Operator Application

GET  /app              → Login page (unauthenticated)
GET  /app/dashboard    → Main dashboard shell (requires auth cookie)
POST /app/auth/login   → Authenticate, set httpOnly JWT cookie
POST /app/auth/logout  → Clear session cookies
POST /app/auth/refresh → Rotate refresh token

The authenticated app is a full single-page React application served
from a single HTML response. All data fetching happens client-side
against the existing /api/v1/* endpoints plus new /app/api/* endpoints.

Auth: JWT (access 15min) + refresh token (30 days) in httpOnly cookies.
      Passwords hashed with bcrypt. Refresh token rotation on every use.

Sections:
  01  Overview          — live stats, system status, SLO meters
  02  Pre-Booking       — inquiry queue, AI draft review, send/edit/reject
  03  Guest Sessions    — active sessions, chat thread, intent metadata
  04  Escalations       — open tickets, team assignment, resolve flow
  05  Knowledge Base    — entries, gaps, test question, approve answers
  06  Vendors           — add/manage vendors, categories, priority/fallback
  07  Team              — invite members, assign escalation roles, permissions
  08  Properties        — connected properties, PMS sync status, per-property KB
  09  Analytics         — resolution rate, intents, LEARN layer, export
  10  Settings          — account, notifications, AI confidence thresholds
"""

import os
import json
import logging
import time
import hmac
import hashlib
import base64
import secrets
import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request, Response, Form, HTTPException, Depends, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.storage import R2StorageError, get_r2_client
from db.models.documents import DocumentModel, ExtractedFieldModel
from app.services.operator.scope_service import get_operator_scope_service

router = APIRouter(prefix="/app", tags=["Operator App"])

logger = logging.getLogger(__name__)
DEFAULT_IMPORT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_scope_service = get_operator_scope_service()


async def _table_columns(db: AsyncSession, table_name: str) -> set[str]:
    from sqlalchemy import text as _text

    rows = await db.execute(
        _text(
            """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
        """
        ),
        {"table": table_name},
    )
    return {str(row[0]) for row in rows.fetchall()}


def _records_from_uploaded_property_file(filename: str, content: bytes) -> list[dict[str, Any]]:
    import csv as _csv

    lower_name = (filename or "").lower()
    if lower_name.endswith(".csv"):
        text_value = content.decode("utf-8-sig", errors="replace")
        return [dict(row) for row in _csv.DictReader(io.StringIO(text_value))]
    if lower_name.endswith(".tsv"):
        text_value = content.decode("utf-8-sig", errors="replace")
        return [dict(row) for row in _csv.DictReader(io.StringIO(text_value), delimiter="\t")]
    if lower_name.endswith(".json"):
        payload = json.loads(content.decode("utf-8"))
        if isinstance(payload, list):
            return [dict(row) for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("properties") or payload.get("rows") or payload.get("items") or []
            return [dict(row) for row in rows if isinstance(row, dict)]
        return []
    if lower_name.endswith(".xlsx") or lower_name.endswith(".xls"):
        import pandas as _pd

        frame = _pd.read_excel(io.BytesIO(content))
        return frame.where(_pd.notnull(frame), None).to_dict(orient="records")
    raise HTTPException(400, "Unsupported file type. Upload CSV, TSV, XLSX, XLS, or JSON.")


def _normalize_document_ingest_hint(document_type: str) -> str:
    hint = (document_type or "").strip().lower()
    mapping = {
        "house_manual": "house_manual",
        "amenities": "amenities",
        "guest_qa": "guest_qa",
        "rental_agreement": "lease",
        "lease": "lease",
        "equipment_warranty": "misc",
        "appliance_manual": "misc",
        "portfolio_policy": "misc",
        "misc": "misc",
    }
    return mapping.get(hint, hint or "misc")


def _coerce_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_coerce_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _coerce_jsonable(v) for k, v in value.items()}
    return str(value)


def _fields_summary(fields: list[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in fields:
        name = str(getattr(field, "field_name", "") or "").strip()
        if not name:
            continue
        value = _coerce_jsonable(getattr(field, "value", None))
        if name in summary:
            existing = summary[name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                summary[name] = [existing, value]
        else:
            summary[name] = value
    return summary


def _document_excerpt(raw_text: Optional[str], limit: int = 1600) -> str:
    text_value = str(raw_text or "").strip()
    if not text_value:
        return ""
    condensed = " ".join(text_value.split())
    return condensed[:limit]


def _serialize_extracted_field(field: Any) -> dict[str, Any]:
    return {
        "field_name": str(getattr(field, "field_name", "") or "").strip(),
        "value": _coerce_jsonable(getattr(field, "value", None)),
        "confidence": str(getattr(getattr(field, "confidence", None), "value", getattr(field, "confidence", "medium"))),
        "source_document_type": getattr(field, "source_document_type", None),
        "source_page": getattr(field, "source_page", None),
        "source_text": getattr(field, "source_text", None),
        "field_id": str(getattr(field, "field_id", "") or ""),
        "extracted_at": getattr(getattr(field, "extracted_at", None), "isoformat", lambda: None)(),
    }


def _document_source_type(filename: str) -> str:
    lower_name = (filename or "").strip().lower()
    if lower_name.endswith(".pdf"):
        return "pdf"
    if lower_name.endswith((".csv", ".tsv", ".xlsx", ".xls")):
        return "spreadsheet"
    return "other"


def _field_confidence_score(field: Any) -> float:
    raw = str(getattr(getattr(field, "confidence", None), "value", getattr(field, "confidence", "medium")) or "medium")
    normalized = raw.strip().lower()
    if normalized == "high":
        return 0.95
    if normalized == "low":
        return 0.60
    return 0.80


def _normalize_candidate_question_key(field_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(field_name or "").strip().lower()).strip("_")


def _default_candidate_question_text(field_name: str) -> str:
    label = str(field_name or "").strip().replace("_", " ")
    label = re.sub(r"\s+", " ", label).strip()
    if not label:
        return "What does this document say?"
    return f"What does the document say about {label}?"


def _candidate_answer_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=True, sort_keys=True)
        except Exception:
            return str(value)
    return str(value).strip()


def _candidate_source_section(field: Any) -> Optional[str]:
    parts: list[str] = []
    source_type = str(getattr(field, "source_document_type", "") or "").strip()
    source_page = getattr(field, "source_page", None)
    if source_type:
        parts.append(source_type)
    if source_page not in (None, ""):
        parts.append(f"page {source_page}")
    return " | ".join(parts) if parts else None


def _document_scope_binding(
    *,
    tenant_id: str,
    scope: str,
    property_row: Optional[dict[str, Any]],
) -> tuple[str, str]:
    if scope == "portfolio":
        return "tenant", tenant_id
    property_id = str((property_row or {}).get("property_id") or "").strip()
    if not property_id:
        raise HTTPException(400, "property-scoped imports require a canonical property_id")
    return "property", property_id


def _build_fact_candidate_payloads(
    *,
    extracted_fields: list[Any],
    source_type: str,
    source_document_id: str,
    source_label: str,
    document_type: str,
    document_class: str,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for field in extracted_fields:
        field_name = str(getattr(field, "field_name", "") or "").strip()
        if not field_name or field_name == "guest_qa_record":
            continue
        answer_text = _candidate_answer_text(getattr(field, "value", None))
        if not answer_text:
            continue
        payloads.append(
            {
                "source_type": source_type,
                "source_document_id": source_document_id,
                "extraction_method": "deterministic",
                "candidate_type": "fact",
                "proposed_question_text": _default_candidate_question_text(field_name),
                "proposed_question_key": _normalize_candidate_question_key(field_name),
                "proposed_answer_text": answer_text,
                "proposed_topic_id": None,
                "proposed_tags": [field_name],
                "proposed_metadata": {
                    "field_name": field_name,
                    "document_type": document_type,
                    "document_class": document_class,
                    "source_label": source_label,
                    "source_page": getattr(field, "source_page", None),
                },
                "confidence": _field_confidence_score(field),
                "evidence_excerpt": getattr(field, "source_text", None),
                "source_section": _candidate_source_section(field),
            }
        )
    return payloads


def _build_asset_candidate_payload(
    *,
    document_type: str,
    filename: str,
    normalized: Any,
    extracted_fields: list[Any],
    asset_type: Optional[str],
    asset_name: Optional[str],
    source_document_id: str,
    source_type: str,
) -> dict[str, Any]:
    field_map = _fields_summary(extracted_fields)
    inferred_asset_type = (asset_type or "").strip().lower() or (
        "warranty" if document_type == "equipment_warranty" else
        "appliance" if document_type == "appliance_manual" else
        "document"
    )
    inferred_asset_name = (asset_name or "").strip() or os.path.splitext(filename)[0] or "Uploaded document"
    excerpt = _document_excerpt(getattr(normalized, "raw_text", None), limit=1500)
    notes_parts = [
        f"Document upload: {filename}",
        f"Document type: {document_type}",
    ]
    if excerpt:
        notes_parts.append(excerpt)

    return {
        "source_type": source_type,
        "source_document_id": source_document_id,
        "extraction_method": "deterministic",
        "candidate_type": "asset",
        "proposed_question_text": inferred_asset_name,
        "proposed_question_key": _normalize_candidate_question_key(inferred_asset_name),
        "proposed_answer_text": "\n\n".join(notes_parts),
        "proposed_topic_id": None,
        "proposed_tags": [inferred_asset_type, "document_upload"],
        "proposed_metadata": {
            "asset_type": inferred_asset_type,
            "asset_name": inferred_asset_name,
            "source": "document_upload",
            "source_document_type": document_type,
            "source_filename": filename,
            "extracted_fields": field_map,
        },
        "confidence": 0.95 if extracted_fields else 0.80,
        "evidence_excerpt": excerpt,
        "source_section": document_type,
    }


async def _persist_source_document(
    db: AsyncSession,
    *,
    tenant_id: str,
    property_id: Optional[str],
    scope: str,
    document_type: str,
    filename: str,
    content: bytes,
    content_type: Optional[str],
    upload_method: str,
    uploaded_by: Optional[str],
    content_hash: str,
) -> tuple[DocumentModel, bool, bool]:
    property_uuid = uuid.UUID(property_id) if property_id else None
    stmt = (
        select(DocumentModel)
        .where(
            DocumentModel.tenant_id == uuid.UUID(tenant_id),
            DocumentModel.scope_type == scope,
            DocumentModel.document_type == document_type,
            DocumentModel.filename == filename,
        )
        .order_by(DocumentModel.version_number.desc(), DocumentModel.uploaded_at.desc())
        .limit(1)
    )
    if property_uuid is None:
        stmt = stmt.where(DocumentModel.property_id.is_(None))
    else:
        stmt = stmt.where(DocumentModel.property_id == property_uuid)

    latest = await db.scalar(stmt)
    if latest and latest.content_hash == content_hash:
        return latest, False, True

    try:
        if latest:
            created = await latest.create_version(
                db,
                content,
                mime_type=content_type,
                uploaded_by=uploaded_by,
                content_hash=content_hash,
                file_size=len(content),
            )
            return created, True, False

        group_id = uuid.uuid4()
        stored = await get_r2_client().upload_file(
            tenant_id,
            str(group_id),
            filename,
            content,
            content_type=content_type,
        )
    except R2StorageError as exc:
        raise HTTPException(502, f"Document storage failed: {exc}") from exc

    row = DocumentModel(
        tenant_id=uuid.UUID(tenant_id),
        property_id=property_uuid,
        document_group_id=group_id,
        scope_type=scope,
        version_number=1,
        document_type=document_type,
        filename=filename,
        file_path=stored.key,
        storage_backend="r2",
        file_size=len(content),
        mime_type=content_type,
        content_hash=content_hash,
        upload_method=upload_method,
        extraction_status="processing",
        uploaded_by=uploaded_by,
    )
    db.add(row)
    await db.flush()
    return row, True, False


async def _save_document_extraction(
    db: AsyncSession,
    *,
    document_row: DocumentModel,
    extraction: Any,
) -> None:
    serialized = [_serialize_extracted_field(field) for field in extraction.fields]
    document_row.extracted_fields = serialized
    document_row.extraction_status = "completed"
    document_row.extraction_error = None if not extraction.errors else "; ".join(str(err) for err in extraction.errors)
    document_row.processed_at = datetime.now(timezone.utc)

    await db.execute(delete(ExtractedFieldModel).where(ExtractedFieldModel.document_id == document_row.id))
    for field, field_payload in zip(extraction.fields, serialized):
        db.add(
            ExtractedFieldModel(
                document_id=document_row.id,
                tenant_id=document_row.tenant_id,
                property_id=document_row.property_id,
                field_name=field_payload["field_name"],
                field_value=field_payload["value"],
                confidence=field_payload["confidence"],
                source_page=field_payload["source_page"],
                source_text=field_payload["source_text"],
            )
        )


def _merge_document_facts(
    facts: dict[str, Any],
    sections: dict[str, Any],
    field_map: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged_facts = dict(facts or {})
    merged_sections = dict(sections or {})

    def _set_fact(key: str, source_key: str) -> None:
        value = field_map.get(source_key)
        if value not in (None, "", [], {}):
            merged_facts[key] = value

    _set_fact("wifi", "wifi_password")
    _set_fact("wifi_network", "wifi_network")
    _set_fact("check_in", "checkin_time")
    _set_fact("check_out", "checkout_time")
    _set_fact("lock_code", "lock_code")
    _set_fact("pets_allowed", "pets_allowed")
    _set_fact("smoking_allowed", "smoking_allowed")
    _set_fact("quiet_hours_start", "quiet_hours_start")
    _set_fact("max_occupancy", "max_occupancy")

    if field_map.get("amenities") not in (None, "", [], {}):
        merged_facts["document_amenities"] = field_map["amenities"]
    if field_map.get("premium_amenities") not in (None, "", [], {}):
        merged_facts["premium_amenities"] = field_map["premium_amenities"]
    if field_map.get("amenity_count") not in (None, "", [], {}):
        merged_facts["amenity_count"] = field_map["amenity_count"]

    if field_map.get("emergency_contacts") not in (None, "", [], {}):
        merged_sections["emergency_contacts"] = field_map["emergency_contacts"]

    return merged_facts, merged_sections


async def _load_property_record_for_code(
    db: AsyncSession,
    tenant_id: str,
    property_code: str,
) -> Optional[dict[str, Any]]:
    from sqlalchemy import text as _text

    property_cols = await _table_columns(db, "properties")
    if "property_code" not in property_cols:
        return None
    select_cols = [
        "property_code",
        "external_id" if "external_id" in property_cols else "NULL::text AS external_id",
        "address_street" if "address_street" in property_cols else "NULL::text AS address_street",
        "community" if "community" in property_cols else "NULL::text AS community",
        "property_id" if "property_id" in property_cols else ("id AS property_id" if "id" in property_cols else "NULL::uuid AS property_id"),
    ]
    row = (
        await db.execute(
            _text(
                f"""
                SELECT {", ".join(select_cols)}
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND property_code = :property_code
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "property_code": property_code},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _import_guest_qa_records(
    db: AsyncSession,
    *,
    tenant_id: str,
    reviewer_id: str,
    scope_type: str,
    scope_target_id: str,
    filename: str,
    extracted_fields: list[Any],
) -> dict[str, Any]:
    import uuid as _uuid

    from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService

    records: list[dict[str, Any]] = []
    for field in extracted_fields:
        if str(getattr(field, "field_name", "") or "") != "guest_qa_record":
            continue
        value = getattr(field, "value", None)
        if not isinstance(value, dict):
            continue
        records.append(
            {
                "question_text": str(value.get("question") or "").strip(),
                "answer_text": str(value.get("answer") or "").strip(),
                "metadata": {
                    "source_document": filename,
                    "category": value.get("category") or "",
                    "document_source": "guest_qa_upload",
                },
            }
        )
    if not records:
        return {"imported_answers": 0, "imported_gaps": 0, "skipped": 0, "total_records": 0}

    service = ScopedKnowledgeService()
    imported_answers = 0
    imported_gaps = 0
    skipped = 0
    total_records = len(records)
    tenant_uuid = _uuid.UUID(tenant_id)
    reviewer_uuid = _uuid.UUID(reviewer_id)
    target_uuid = _uuid.UUID(scope_target_id)

    for record in records:
        question = str(record.get("question_text") or "").strip()
        answer = str(record.get("answer_text") or "").strip()
        if not question:
            skipped += 1
            continue
        if not answer:
            skipped += 1
            continue
        category = str((record.get("metadata") or {}).get("category") or "").strip()
        tags = [category.lower().replace(" ", "_")] if category else []
        await service.write_scoped_knowledge(
            session=db,
            tenant_id=tenant_uuid,
            user_id=reviewer_uuid,
            scope_type=scope_type,
            scope_target_id=target_uuid,
            topic_id=None,
            question_text=question,
            answer_text=answer,
            tags=tags,
            source="historical_import",
            metadata=record.get("metadata") or {},
        )
        imported_answers += 1

    return {
        "imported_answers": imported_answers,
        "imported_gaps": imported_gaps,
        "skipped": skipped,
        "total_records": total_records,
    }


async def _upsert_document_asset(
    db: AsyncSession,
    *,
    tenant_id: str,
    property_code: str,
    document_type: str,
    filename: str,
    normalized: Any,
    extracted_fields: list[Any],
    asset_type: Optional[str],
    asset_name: Optional[str],
) -> dict[str, Any]:
    from app.services.operator.property_asset_service import get_operator_property_asset_service

    field_map = _fields_summary(extracted_fields)
    inferred_asset_type = (asset_type or "").strip().lower() or (
        "warranty" if document_type == "equipment_warranty" else
        "appliance" if document_type == "appliance_manual" else
        "document"
    )
    inferred_asset_name = (asset_name or "").strip() or os.path.splitext(filename)[0] or "Uploaded document"
    excerpt = _document_excerpt(getattr(normalized, "raw_text", None), limit=1500)
    notes_parts = [
        f"Document upload: {filename}",
        f"Document type: {document_type}",
    ]
    if excerpt:
        notes_parts.append(excerpt)

    metadata = {
        "source": "document_upload",
        "source_document_type": document_type,
        "source_filename": filename,
        "extracted_fields": field_map,
    }

    return await get_operator_property_asset_service().upsert_asset(
        db,
        tenant_id,
        property_code=property_code,
        asset_type=inferred_asset_type,
        asset_name=inferred_asset_name,
        notes="\n\n".join(notes_parts),
        metadata=metadata,
    )


class PropertyIdentityLinkRequest(BaseModel):
    canonical_property_code: str
    ref_value: str
    provider: str = "internal"
    ref_kind: str = "alias"
    source: str = "manual_property_link"
    platform_listing_id: Optional[str] = None
    property_name: Optional[str] = None
    display_name: Optional[str] = None
    marketing_name: Optional[str] = None


class PropertyProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    marketing_name: Optional[str] = None
    preferred_address: Optional[str] = None
    source: str = "manual_profile_update"


class PropertyLinkReviewDecisionRequest(BaseModel):
    canonical_property_code: Optional[str] = None


class PropertyImportUploadResponse(BaseModel):
    ok: bool
    count: int

# ─── JWT HELPERS ────────────────────────────────────────────────────────────

# Warn loudly if JWT_SECRET not set — SOC 2 CC6 blocker
_JWT_SECRET_RAW = os.getenv("JWT_SECRET", "")
if not _JWT_SECRET_RAW:
    import logging as _seclog
    _seclog.getLogger(__name__).critical(
        "[Security] JWT_SECRET env var not set! All sessions invalidated on every restart. "
        "Set JWT_SECRET in Railway immediately."
    )
_JWT_SECRET = _JWT_SECRET_RAW or secrets.token_hex(32)
_ACCESS_TTL = 15 * 60       # 15 minutes
_REFRESH_TTL = 30 * 24 * 3600  # 30 days
# ─── BRUTE FORCE PROTECTION ────────────────────────────────────────────
# In-process store. Move to Redis for multi-replica deployments.
import collections as _col
import threading as _thr

_login_attempts: dict = _col.defaultdict(list)   # ip → [timestamps]
_login_lock = _thr.Lock()
_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
_LOCKOUT_SECONDS = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15")) * 60

# Revoked refresh token JTIs (in-memory — replace with Redis for persistence)
_revoked_jtis: set = set()
_revoked_lock = _thr.Lock()


def _check_lockout(ip: str) -> None:
    """Raise 429 if IP exceeded login attempt limit."""
    now = time.time()
    with _login_lock:
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_SECONDS]
        if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
            raise HTTPException(
                429,
                f"Too many login attempts. Try again in {_LOCKOUT_SECONDS // 60} minutes."
            )


def _record_failure(ip: str) -> None:
    with _login_lock:
        _login_attempts[ip].append(time.time())


def _clear_attempts(ip: str) -> None:
    with _login_lock:
        _login_attempts.pop(ip, None)


def _revoke_jti(jti: str) -> None:
    with _revoked_lock:
        _revoked_jtis.add(jti)


def _is_revoked(jti: str) -> bool:
    with _revoked_lock:
        return jti in _revoked_jtis


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(payload: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(_JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def _verify(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        expected = _b64(hmac.new(
            _JWT_SECRET.encode(),
            f"{header}.{body}".encode(),
            hashlib.sha256
        ).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        jti = payload.get("jti")
        if jti and _is_revoked(jti):
            return None
        return payload
    except Exception:
        return None


def _make_access_token(
    operator_id: str,
    email: str,
    role: str,
    tenant_id: Optional[str] = None,
    scoped_operator_id: Optional[str] = None,
) -> str:
    """
    Build an access token.

    `operator_id` is the row id from operator_accounts (or sa_001 for super admins).
    `tenant_id`   is the tenant_id UUID from operator_accounts — used for all
                  DB queries that scope data by tenant. Always pass this for
                  DB-backed operators so _get_operator_context returns the
                  correct tenant_id rather than falling back to operator_id.
    `scoped_operator_id` is set when a super_admin scopes into a specific tenant.
    """
    payload = {
        "sub": operator_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + _ACCESS_TTL,
        "iat": int(time.time()),
        "type": "access",
    }
    if tenant_id:
        payload["tid"] = tenant_id
    if scoped_operator_id:
        payload["scoped_op"] = scoped_operator_id
    return _sign(payload)


def _make_refresh_token(
    operator_id: str,
    email: str,
    role: str,
    tenant_id: Optional[str] = None,
    scoped_operator_id: Optional[str] = None,
) -> str:
    payload = {
        "sub": operator_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + _REFRESH_TTL,
        "iat": int(time.time()),
        "jti": secrets.token_hex(16),
        "type": "refresh",
    }
    if tenant_id:
        payload["tid"] = tenant_id
    if scoped_operator_id:
        payload["scoped_op"] = scoped_operator_id
    return _sign(payload)


def _get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    payload = _verify(token)
    if not payload:
        return None
    if payload.get("role") == "super_admin":
        scoped_op = request.cookies.get("oyvoda_scoped_op")
        scoped_tid = request.cookies.get("oyvoda_scoped_tid")
        if scoped_op:
            payload["scoped_op"] = scoped_op
        if scoped_tid:
            payload["tid"] = scoped_tid
            payload["tenant_id"] = scoped_tid
    return payload


def _should_use_secure_cookies(request: Request) -> bool:
    """
    Use Secure cookies everywhere except plain local HTTP development.

    Local smoke tests run against http://localhost:8000 / 127.0.0.1:8000,
    where browsers correctly refuse Secure cookies. In production we still
    want Secure, including behind a proxy that forwards https via headers.
    """
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded_proto == "https":
        return True
    if request.url.scheme == "https":
        return True
    host = (request.url.hostname or "").strip().lower()
    return host not in {"localhost", "127.0.0.1"}


# ─── AUTH ROUTES ─────────────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(request: Request, response: Response):
    """Email + password login. Returns httpOnly JWT cookies."""
    try:
        data = await request.json()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
    except Exception:
        raise HTTPException(400, "Invalid request body")

    # ── Super admin accounts (Oyvoda staff — cross-operator access) ──────────
    # Set SUPER_ADMIN_1_EMAIL, SUPER_ADMIN_1_PASSWORD in Railway.
    # Super admins get role="super_admin" and can view all operators.
    SUPER_ADMINS = {}
    for _i in range(1, 4):
        _sa_email = os.getenv(f"SUPER_ADMIN_{_i}_EMAIL", "").strip().lower()
        _sa_pw    = os.getenv(f"SUPER_ADMIN_{_i}_PASSWORD", "")
        _sa_name  = os.getenv(f"SUPER_ADMIN_{_i}_NAME", "Oyvoda Admin")
        if _sa_email and _sa_pw:
            SUPER_ADMINS[_sa_email] = {
                "id": f"sa_{_i:03d}",
                "password": _sa_pw,
                "name": _sa_name,
                "company": "Oyvoda",
                "role": "super_admin",
                "properties": 0,
                "pms": "All",
            }

    # ── DB-backed operator auth (priority 1) ────────────────────────────────
    # Check super admin env var accounts first, then DB operator accounts.
    # Railway OPERATOR_N_* env vars are no longer needed for regular operators.
    ip = request.client.host if request.client else "unknown"
    secure_cookies = _should_use_secure_cookies(request)
    _check_lockout(ip)

    # Super admin check (env vars only — never in DB)
    from app.core.security_layer import security as _sec_layer, AuditEventType
    sa_op = SUPER_ADMINS.get(email)
    if sa_op:
        stored_pw = sa_op["password"]
        if stored_pw.startswith("$2b$") or stored_pw.startswith("$2a$"):
            pw_valid = _sec_layer.verify_password(password, stored_pw)
        else:
            pw_valid = secrets.compare_digest(password, stored_pw)
        if not pw_valid:
            _record_failure(ip)
            _sec_layer.log_login(email, success=False, ip=ip, reason="wrong_password")
            raise HTTPException(401, "Invalid email or password")
        _clear_attempts(ip)
        _sec_layer.log_login(sa_op["id"], success=True, ip=ip)

        # Build all_operators list for super admin switcher
        all_operators_list = []
        try:
            from app.core.database import get_db_session
            from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
            async with get_db_session() as _db:
                all_operators_list = await _gas().list_all_operators(_db)
        except Exception as _ole:
            logger.warning("[Auth] Could not load operators list: %s", _ole)

        is_super_admin = True
        access  = _make_access_token(sa_op["id"], email, "super_admin")
        refresh = _make_refresh_token(sa_op["id"], email, "super_admin")
        resp = JSONResponse({"ok": True, "operator": {
            "id": sa_op["id"], "email": email, "name": sa_op["name"],
            "company": sa_op["company"], "role": "super_admin",
            "is_super_admin": True, "properties": 0, "pms": "All",
            "all_operators": all_operators_list,
        }})
        resp.set_cookie("oyvoda_access", access, httponly=True, secure=secure_cookies,
                        samesite="lax", max_age=_ACCESS_TTL, path="/")
        resp.set_cookie("oyvoda_refresh", refresh, httponly=True, secure=secure_cookies,
                        samesite="lax", max_age=_REFRESH_TTL, path="/app/auth")
        return resp

    # DB operator / team member auth
    try:
        from app.core.database import get_db_session
        from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
        async with get_db_session() as _db:
            auth_user = await _gas().authenticate(_db, email, password)
    except Exception as _dbe:
        logger.error("[Auth] DB auth failed: %s", _dbe)
        auth_user = None

    if auth_user:
        _clear_attempts(ip)
        _sec_layer.log_login(auth_user.id, success=True, ip=ip)
        access  = _make_access_token(auth_user.operator_id, email, auth_user.role, tenant_id=auth_user.tenant_id)
        refresh = _make_refresh_token(auth_user.operator_id, email, auth_user.role, tenant_id=auth_user.tenant_id)
        resp = JSONResponse({"ok": True, "operator": {
            "id":                  auth_user.operator_id,
            "email":               email,
            "name":                auth_user.name,
            "company":             auth_user.company_name,
            "role":                auth_user.role,
            "is_super_admin":      False,
            "properties":          auth_user.property_count,
            "pms":                 "Escapia",
            "onboarding_complete": auth_user.onboarding_complete,
            "tenant_id":           auth_user.tenant_id,
            "all_operators":       [],
        }})
        resp.set_cookie("oyvoda_access", access, httponly=True, secure=secure_cookies,
                        samesite="lax", max_age=_ACCESS_TTL, path="/")
        resp.set_cookie("oyvoda_refresh", refresh, httponly=True, secure=secure_cookies,
                        samesite="lax", max_age=_REFRESH_TTL, path="/app/auth")
        return resp

    # Legacy Railway env var operator fallback (for existing OPERATOR_1_* accounts
    # until they migrate to DB accounts)
    # Operator credentials loaded from Railway env vars
    DEMO_OPERATORS = {}
    for _i in range(1, 6):
        _email = os.getenv(f"OPERATOR_{_i}_EMAIL", "").strip().lower()
        _pw    = os.getenv(f"OPERATOR_{_i}_PASSWORD", "")
        _oid   = os.getenv(f"OPERATOR_{_i}_ID", f"op_{_i:03d}")
        _name  = os.getenv(f"OPERATOR_{_i}_NAME", "Operator")
        _co    = os.getenv(f"OPERATOR_{_i}_COMPANY", "Properties")
        if _email and _pw:
            DEMO_OPERATORS[_email] = {
                "id": _oid, "password": _pw, "name": _name,
                "company": _co, "role": "owner", "properties": 50, "pms": "Escapia"
            }
    # Fallback demo account only if no env operators configured
    if not DEMO_OPERATORS:
        DEMO_OPERATORS["operator@oyvoda.com"] = {
            "id": "op_001", "password": "OyvodaDemo2026!",
            "name": "Demo Operator", "company": "Demo Properties",
            "role": "owner", "properties": 0, "pms": "Escapia"
        }

    # Legacy Railway env var fallback — check remaining env operators
    op = DEMO_OPERATORS.get(email)
    if not op:
        _record_failure(ip)
        raise HTTPException(401, "Invalid email or password")

    # Support both bcrypt hashes and plaintext (plaintext only during migration)
    # Once all Railway passwords are bcrypt hashes, remove the plaintext fallback.
    from app.core.security_layer import security, AuditEventType
    stored_pw = op["password"]
    if stored_pw.startswith("$2b$") or stored_pw.startswith("$2a$"):
        # bcrypt hash — proper verification
        pw_valid = security.verify_password(password, stored_pw)
    else:
        # Plaintext fallback (temporary — migrate to bcrypt in Railway)
        pw_valid = secrets.compare_digest(password, stored_pw)

    if not pw_valid:
        _record_failure(ip)
        security.log_login(email, success=False, ip=ip, reason="wrong_password")
        raise HTTPException(401, "Invalid email or password")

    _clear_attempts(ip)  # Reset on successful login
    security.log_login(op["id"], success=True, ip=ip)

    is_super_admin = op["role"] == "super_admin"

    # For super admins, build the full operator list so the dashboard
    # can render the operator switcher immediately without a second fetch.
    all_operators_list = []
    if is_super_admin:
        for _i in range(1, 6):
            _oe = os.getenv(f"OPERATOR_{_i}_EMAIL", "").strip().lower()
            _oid2 = os.getenv(f"OPERATOR_{_i}_ID", f"op_{_i:03d}")
            _oname = os.getenv(f"OPERATOR_{_i}_NAME", "")
            _oco = os.getenv(f"OPERATOR_{_i}_COMPANY", "")
            if _oe and _oname:
                all_operators_list.append({
                    "id": _oid2,
                    "email": _oe,
                    "name": _oname,
                    "company": _oco,
                })

    access = _make_access_token(op["id"], email, op["role"])
    refresh = _make_refresh_token(op["id"], email, op["role"])

    resp = JSONResponse({
        "ok": True,
        "operator": {
            "id": op["id"],
            "email": email,
            "name": op["name"],
            "company": op["company"],
            "role": op["role"],
            "is_super_admin": is_super_admin,
            "properties": op["properties"],
            "pms": op["pms"],
            "all_operators": all_operators_list,
        }
    })
    resp.set_cookie("oyvoda_access", access, httponly=True, secure=secure_cookies,
                    samesite="lax", max_age=_ACCESS_TTL, path="/")
    resp.set_cookie("oyvoda_refresh", refresh, httponly=True, secure=secure_cookies,
                    samesite="lax", max_age=_REFRESH_TTL, path="/app/auth")
    return resp


@router.post("/auth/logout")
async def logout(request: Request):
    # Revoke the refresh token JTI so it cannot be reused
    refresh_token = request.cookies.get("oyvoda_refresh")
    if refresh_token:
        payload = _verify(refresh_token)
        if payload and "jti" in payload:
            _revoke_jti(payload["jti"])
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("oyvoda_access", path="/")
    resp.delete_cookie("oyvoda_refresh", path="/app/auth")
    resp.delete_cookie("oyvoda_scoped_op", path="/")
    resp.delete_cookie("oyvoda_scoped_tid", path="/")
    return resp


@router.post("/auth/refresh")
async def refresh_token(request: Request):
    token = request.cookies.get("oyvoda_refresh")
    if not token:
        raise HTTPException(401, "No refresh token")
    secure_cookies = _should_use_secure_cookies(request)
    payload = _verify(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid or expired refresh token")
    if _is_revoked(payload.get("jti", "")):
        raise HTTPException(401, "Refresh token has been revoked")

    operator_id = payload["sub"]
    email = payload.get("email", "")
    role = payload.get("role", "owner")
    scoped_operator_id = payload.get("scoped_op")
    tenant_id = payload.get("tid")

    if payload.get("jti"):
        _revoke_jti(payload["jti"])

    new_access = _make_access_token(
        operator_id,
        email,
        role,
        tenant_id=tenant_id,
        scoped_operator_id=scoped_operator_id,
    )
    new_refresh = _make_refresh_token(
        operator_id,
        email,
        role,
        tenant_id=tenant_id,
        scoped_operator_id=scoped_operator_id,
    )

    resp = JSONResponse({"ok": True})
    resp.set_cookie("oyvoda_access", new_access, httponly=True, secure=secure_cookies,
                    samesite="lax", max_age=_ACCESS_TTL, path="/")
    resp.set_cookie("oyvoda_refresh", new_refresh, httponly=True, secure=secure_cookies,
                    samesite="lax", max_age=_REFRESH_TTL, path="/app/auth")
    return resp


async def _build_session_operator(db: AsyncSession, payload: dict) -> dict:
    """Return the effective operator session for the current JWT."""
    from sqlalchemy import text
    from app.services.auth.operator_auth_service import get_operator_auth_service as _gas

    role = payload.get("role", "owner")
    scoped_operator_id = payload.get("scoped_op")
    all_operators = []

    if role == "super_admin":
        try:
            all_operators = await _gas().list_all_operators(db)
        except Exception as exc:
            logger.warning("[Auth] Could not load operators list for session: %s", exc)

        if scoped_operator_id:
            result = await db.execute(text("""
                SELECT id, tenant_id, email, owner_name, company_name, pms,
                       property_count, onboarding_complete
                FROM operator_accounts
                WHERE id = CAST(:id AS uuid)
                LIMIT 1
            """), {"id": scoped_operator_id})
            row = result.fetchone()
            if not row:
                raise HTTPException(404, "Scoped operator not found")
            return {
                "id": str(row.id),
                "email": row.email,
                "name": row.owner_name,
                "company": row.company_name,
                "role": "owner",
                "is_super_admin": True,
                "impersonating": True,
                "impersonated_operator_id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "properties": row.property_count or 0,
                "pms": row.pms or "Escapia",
                "onboarding_complete": bool(row.onboarding_complete),
                "admin_email": payload.get("email", ""),
                "all_operators": all_operators,
            }

        return {
            "id": payload.get("sub"),
            "email": payload.get("email", ""),
            "name": "Oyvoda Admin",
            "company": "Oyvoda",
            "role": "super_admin",
            "is_super_admin": True,
            "impersonating": False,
            "properties": 0,
            "pms": "All",
            "all_operators": all_operators,
        }

    operator_id = payload.get("sub")
    result = await db.execute(text("""
        SELECT id, tenant_id, email, owner_name, company_name, pms,
               property_count, onboarding_complete
        FROM operator_accounts
        WHERE id = CAST(:id AS uuid)
        LIMIT 1
    """), {"id": operator_id})
    row = result.fetchone()
    if row:
        return {
            "id": str(row.id),
            "email": row.email,
            "name": row.owner_name,
            "company": row.company_name,
            "role": role,
            "is_super_admin": False,
            "impersonating": False,
            "tenant_id": str(row.tenant_id),
            "properties": row.property_count or 0,
            "pms": row.pms or "Escapia",
            "onboarding_complete": bool(row.onboarding_complete),
            "all_operators": [],
        }

    return {
        "id": operator_id,
        "email": payload.get("email", ""),
        "name": "Operator",
        "company": "Properties",
        "role": role,
        "is_super_admin": False,
        "impersonating": False,
        "tenant_id": payload.get("tid") or operator_id,
        "properties": 0,
        "pms": "Escapia",
        "all_operators": [],
    }


# ─── PASSWORD RESET + CHANGE PASSWORD ───────────────────────────────────────
# Three flows:
#   1. Forgot password (unauthenticated): POST /app/auth/forgot-password
#      → always 200 (no email enumeration), sends reset email if operator exists
#   2. Reset with token (unauthenticated): POST /app/auth/reset-password
#      → validates token, updates password_hash, revokes all sessions
#   3. Change password (authenticated): POST /app/auth/change-password
#      → requires current password, for in-app password changes
#
# Reset tokens are 32 random bytes base64url-encoded. Only the SHA-256 of the
# token is stored; the raw token is only ever in the reset email URL.
# ─────────────────────────────────────────────────────────────────────────────

_RESET_TOKEN_TTL_SECONDS = 60 * 60  # 1 hour
_RESET_RATE_LIMIT_PER_EMAIL = 5     # max 5 reset requests per email per hour
_RESET_RATE_LIMIT_PER_IP = 20       # max 20 reset requests per IP per hour

# In-memory rate limiter (acceptable for single-replica deployment; move to
# Redis if we ever scale horizontally).
_reset_email_attempts: dict = _col.defaultdict(list)   # email -> [timestamps]
_reset_ip_attempts: dict = _col.defaultdict(list)      # ip -> [timestamps]
_reset_lock = _thr.Lock()


def _check_reset_rate_limit(email: str, ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    cutoff = now - 3600
    with _reset_lock:
        _reset_email_attempts[email] = [t for t in _reset_email_attempts[email] if t > cutoff]
        _reset_ip_attempts[ip] = [t for t in _reset_ip_attempts[ip] if t > cutoff]
        if len(_reset_email_attempts[email]) >= _RESET_RATE_LIMIT_PER_EMAIL:
            return False
        if len(_reset_ip_attempts[ip]) >= _RESET_RATE_LIMIT_PER_IP:
            return False
        _reset_email_attempts[email].append(now)
        _reset_ip_attempts[ip].append(now)
    return True


def _hash_reset_token(raw_token: str) -> str:
    """SHA-256 of the raw token — what we actually store in the DB."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _send_reset_email_bg(to_email: str, to_name: str, reset_url: str) -> None:
    """Fire-and-forget reset email via SendGrid. No-op if SENDGRID_API_KEY unset."""
    import threading
    def _send():
        try:
            sgkey = os.getenv("SENDGRID_API_KEY", "")
            if not sgkey:
                logger.warning("[PasswordReset] SENDGRID_API_KEY not set — cannot send reset email to %s", to_email)
                return
            import httpx as _hx
            _hx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sgkey}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{
                        "to": [{"email": to_email, "name": to_name or to_email}],
                        "subject": "Reset your Oyvoda password",
                    }],
                    "from": {"email": "no-reply@oyvoda.com", "name": "Oyvoda"},
                    "content": [{
                        "type": "text/plain",
                        "value": (
                            f"Hi {to_name or ''},\n\n"
                            f"Someone requested a password reset for your Oyvoda account.\n\n"
                            f"Click here to reset your password (link expires in 1 hour):\n"
                            f"{reset_url}\n\n"
                            f"If you didn't request this, you can safely ignore this email — "
                            f"your password won't change.\n\n— The Oyvoda Team"
                        ),
                    }],
                },
                timeout=10.0,
            )
        except Exception as e:
            logger.warning("[PasswordReset] SendGrid send failed for %s: %s", to_email, e)
    threading.Thread(target=_send, daemon=True).start()


@router.post("/auth/forgot-password")
async def forgot_password(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Accept an email, generate a reset token if the operator exists, email it.
    Always returns 200 with the same message regardless of whether the email
    exists — this prevents attackers from enumerating registered accounts.

    Body: {"email": "operator@example.com"}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        # Even on bad input we return the success-shaped response — don't leak
        # validity info. But skip the DB write.
        return {"ok": True, "message": "If that email is registered, a reset link has been sent."}

    ip = request.client.host if request.client else "unknown"
    if not _check_reset_rate_limit(email, ip):
        logger.warning("[PasswordReset] Rate-limited email=%s ip=%s", email, ip)
        # Same response shape — don't leak rate-limit state either
        return {"ok": True, "message": "If that email is registered, a reset link has been sent."}

    # Look up the operator (ONLY operator_accounts, not team members — team
    # members without activated passwords should use their invite link instead)
    from sqlalchemy import text as _text
    row = (await db.execute(
        _text("SELECT id, email, owner_name FROM operator_accounts WHERE email = :e AND status = 'active' LIMIT 1"),
        {"e": email},
    )).fetchone()

    if row:
        # Invalidate any prior unused tokens for this operator (prevents stockpiling)
        await db.execute(
            _text("UPDATE password_reset_tokens SET used_at = NOW() WHERE operator_id = :oid AND used_at IS NULL"),
            {"oid": str(row.id)},
        )

        # Generate a cryptographically random token. 32 bytes → 43 chars url-safe
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.utcnow() + timedelta(seconds=_RESET_TOKEN_TTL_SECONDS)

        await db.execute(
            _text("""
                INSERT INTO password_reset_tokens
                    (operator_id, token_hash, expires_at, ip_address, user_agent)
                VALUES (:oid, :hash, :exp, :ip, :ua)
            """),
            {
                "oid":   str(row.id),
                "hash":  token_hash,
                "exp":   expires_at,
                "ip":    ip,
                "ua":    (request.headers.get("user-agent") or "")[:500],
            },
        )
        await db.commit()

        base_url = os.getenv("BASE_URL", "https://oyvoda.com")
        reset_url = f"{base_url}/app/reset-password?token={raw_token}"
        _send_reset_email_bg(row.email, row.owner_name or "", reset_url)

        logger.info("[PasswordReset] Token generated for operator=%s ip=%s", row.id, ip)
    else:
        # Log the attempt for audit but don't reveal it to the client
        logger.info("[PasswordReset] Forgot-password attempt for unknown email=%s ip=%s", email, ip)

    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@router.post("/auth/reset-password")
async def reset_password(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Validate a reset token and set the new password atomically.

    Body: {"token": "...", "new_password": "..."}

    On success: updates password_hash, marks token used, revokes the
    operator's existing refresh tokens (forces re-login everywhere).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    raw_token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""

    if not raw_token:
        raise HTTPException(400, "Reset token is required")
    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if len(new_password) > 200:
        raise HTTPException(400, "Password is too long")

    token_hash = _hash_reset_token(raw_token)

    from sqlalchemy import text as _text
    # Look up the token — must be unused and unexpired
    row = (await db.execute(
        _text("""
            SELECT t.token_id, t.operator_id, t.expires_at, t.used_at,
                   o.email, o.owner_name
            FROM password_reset_tokens t
            JOIN operator_accounts o ON o.id = t.operator_id
            WHERE t.token_hash = :h
            LIMIT 1
        """),
        {"h": token_hash},
    )).fetchone()

    if not row:
        raise HTTPException(400, "Invalid or expired reset link. Request a new one.")
    if row.used_at is not None:
        raise HTTPException(400, "This reset link has already been used. Request a new one.")
    if datetime.utcnow() > row.expires_at.replace(tzinfo=None):
        raise HTTPException(400, "This reset link has expired. Request a new one.")

    # Hash the new password using the same function the app's login uses
    from app.core.security_layer import hash_password
    new_hash = hash_password(new_password)

    # Atomic update: mark token used AND update password. If either fails,
    # both roll back (prevents the race where the token gets consumed but
    # the password update fails).
    await db.execute(
        _text("""
            UPDATE password_reset_tokens
            SET used_at = NOW()
            WHERE token_id = :tid
        """),
        {"tid": str(row.token_id)},
    )
    await db.execute(
        _text("""
            UPDATE operator_accounts
            SET password_hash = :h, updated_at = NOW()
            WHERE id = :oid
        """),
        {"h": new_hash, "oid": str(row.operator_id)},
    )
    # Invalidate all other unused reset tokens for this operator too — if
    # they had multiple pending resets, consuming one kills the rest.
    await db.execute(
        _text("""
            UPDATE password_reset_tokens
            SET used_at = NOW()
            WHERE operator_id = :oid AND used_at IS NULL
        """),
        {"oid": str(row.operator_id)},
    )
    await db.commit()

    # Note: we can't revoke refresh tokens by JTI here because we don't
    # track operator_id → JTI. The password change itself invalidates any
    # saved browser sessions on the NEXT request since they'd fail auth.
    # TODO: add refresh-token audit table and revoke by operator_id on reset.

    logger.info("[PasswordReset] Password reset completed for operator=%s", row.operator_id)
    return {"ok": True, "message": "Password updated. You can now sign in with your new password."}


@router.post("/auth/change-password")
async def change_password(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    In-app password change for authenticated users. Requires current
    password (prevents a stolen session cookie from being used to lock
    the real operator out).

    Body: {"current_password": "...", "new_password": "..."}
    """
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    operator_id = user.get("scoped_op") or user.get("sub") or ""
    if not operator_id:
        raise HTTPException(401, "Not authenticated")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if not current_password:
        raise HTTPException(400, "Current password is required")
    if len(new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if len(new_password) > 200:
        raise HTTPException(400, "New password is too long")
    if current_password == new_password:
        raise HTTPException(400, "New password must be different from current password")

    from sqlalchemy import text as _text
    from app.core.security_layer import hash_password, verify_password

    row = (await db.execute(
        _text("SELECT password_hash, email FROM operator_accounts WHERE id = :oid LIMIT 1"),
        {"oid": operator_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "Account not found")

    if not verify_password(current_password, row.password_hash):
        # Rate-limit brute force by treating this like a login failure
        ip = request.client.host if request.client else "unknown"
        _record_failure(ip)
        raise HTTPException(401, "Current password is incorrect")

    new_hash = hash_password(new_password)
    await db.execute(
        _text("UPDATE operator_accounts SET password_hash = :h, updated_at = NOW() WHERE id = :oid"),
        {"h": new_hash, "oid": operator_id},
    )
    await db.commit()

    logger.info("[PasswordReset] Password changed by operator=%s", operator_id)
    return {"ok": True, "message": "Password updated."}


# ─── PASSWORD RESET PAGES (HTML) ────────────────────────────────────────────

FORGOT_PASSWORD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forgot Password — Oyvoda</title>
<meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column}
.wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px;position:relative}
.card{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.15);border-radius:20px;padding:48px;width:100%;max-width:440px;box-shadow:0 32px 80px rgba(0,0,0,0.5)}
.logo{font-family:'Cormorant Garamond',serif;font-size:28px;color:#f0ebe3;text-align:center;display:block;text-decoration:none;margin-bottom:8px}
.sub{font-size:13px;color:rgba(240,235,227,0.4);margin-bottom:28px;text-align:center;font-weight:300}
.form-label{display:block;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.4);margin-bottom:8px}
.form-input{width:100%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px 16px;font-size:14px;color:#f0ebe3;font-family:'DM Sans',sans-serif;outline:none}
.form-input:focus{border-color:rgba(200,120,50,0.4);background:rgba(255,255,255,0.06)}
.btn{width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;padding:14px;font-size:14px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:20px}
.btn:hover{background:#e09040}
.btn:disabled{opacity:0.5;cursor:not-allowed}
.msg{margin-top:16px;padding:12px 14px;border-radius:10px;font-size:13px;display:none}
.msg.ok{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);color:#86efac;display:block}
.msg.err{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);color:#fca5a5;display:block}
.hr{border:none;border-top:1px solid rgba(255,255,255,0.06);margin:24px 0}
.foot{text-align:center;font-size:12px;color:rgba(240,235,227,0.3)}
.foot a{color:rgba(240,235,227,0.5);text-decoration:none}
.foot a:hover{color:rgba(240,235,227,0.8)}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <a href="/" class="logo">oyvoda</a>
    <div class="sub">Reset your password</div>
    <div style="font-size:13px;color:rgba(240,235,227,0.65);line-height:1.6;margin-bottom:24px">
      Enter the email you use to sign in. If we have an account for you, we'll send a link to reset your password.
    </div>
    <label class="form-label">Email address</label>
    <input class="form-input" id="email" type="email" placeholder="you@example.com" autocomplete="email" autofocus>
    <button class="btn" id="submit" onclick="doSubmit()">Send reset link →</button>
    <div class="msg" id="msg"></div>
    <hr class="hr">
    <div class="foot"><a href="/app">← Back to sign in</a></div>
  </div>
</div>
<script>
document.addEventListener('keydown', function(e) { if (e.key === 'Enter') doSubmit(); });
async function doSubmit() {
  const email = document.getElementById('email').value.trim();
  const btn = document.getElementById('submit');
  const msg = document.getElementById('msg');
  if (!email) { msg.className = 'msg err'; msg.textContent = 'Please enter your email.'; return; }
  btn.disabled = true;
  btn.textContent = 'Sending...';
  try {
    const r = await fetch('/app/auth/forgot-password', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({email: email}),
    });
    const d = await r.json();
    msg.className = 'msg ok';
    msg.textContent = d.message || 'If that email is registered, a reset link has been sent. Check your inbox.';
    btn.textContent = 'Link sent';
  } catch(e) {
    msg.className = 'msg err';
    msg.textContent = 'Something went wrong. Please try again.';
    btn.disabled = false;
    btn.textContent = 'Send reset link →';
  }
}
</script>
</body></html>"""


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_page(request: Request):
    """Public page — user enters email to request a reset link."""
    return HTMLResponse(content=FORGOT_PASSWORD_HTML)


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_page(request: Request):
    """
    Public page — user clicks from email and lands here with ?token=... .
    We don't verify the token server-side on the GET (reserving that for
    the POST). This way the page always renders the same shape; invalid
    tokens just fail on submit.
    """
    raw_token = request.query_params.get("token", "").strip()
    # Just pass the token through to the page — validation happens on POST
    safe_token = raw_token.replace('"', "").replace("'", "").replace("<", "").replace(">", "")[:512]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reset Password — Oyvoda</title>
<meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column}}
.wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px}}
.card{{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.15);border-radius:20px;padding:48px;width:100%;max-width:440px;box-shadow:0 32px 80px rgba(0,0,0,0.5)}}
.logo{{font-family:'Cormorant Garamond',serif;font-size:28px;color:#f0ebe3;text-align:center;display:block;text-decoration:none;margin-bottom:8px}}
.sub{{font-size:13px;color:rgba(240,235,227,0.4);margin-bottom:28px;text-align:center;font-weight:300}}
.form-label{{display:block;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.4);margin-bottom:8px}}
.form-group{{margin-bottom:16px}}
.form-input{{width:100%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px 16px;font-size:14px;color:#f0ebe3;font-family:'DM Sans',sans-serif;outline:none}}
.form-input:focus{{border-color:rgba(200,120,50,0.4);background:rgba(255,255,255,0.06)}}
.form-hint{{font-size:11px;color:rgba(240,235,227,0.35);margin-top:6px}}
.btn{{width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;padding:14px;font-size:14px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:8px}}
.btn:hover{{background:#e09040}}
.btn:disabled{{opacity:0.5;cursor:not-allowed}}
.msg{{margin-top:16px;padding:12px 14px;border-radius:10px;font-size:13px;display:none}}
.msg.ok{{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);color:#86efac;display:block}}
.msg.err{{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);color:#fca5a5;display:block}}
.hr{{border:none;border-top:1px solid rgba(255,255,255,0.06);margin:24px 0}}
.foot{{text-align:center;font-size:12px;color:rgba(240,235,227,0.3)}}
.foot a{{color:rgba(240,235,227,0.5);text-decoration:none}}
.foot a:hover{{color:rgba(240,235,227,0.8)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <a href="/" class="logo">oyvoda</a>
    <div class="sub">Choose a new password</div>
    <input type="hidden" id="token" value="{safe_token}">
    <div class="form-group">
      <label class="form-label">New password</label>
      <input class="form-input" id="pw1" type="password" autocomplete="new-password" autofocus>
      <div class="form-hint">At least 8 characters.</div>
    </div>
    <div class="form-group">
      <label class="form-label">Confirm new password</label>
      <input class="form-input" id="pw2" type="password" autocomplete="new-password">
    </div>
    <button class="btn" id="submit" onclick="doSubmit()">Update password →</button>
    <div class="msg" id="msg"></div>
    <hr class="hr">
    <div class="foot"><a href="/app">← Back to sign in</a></div>
  </div>
</div>
<script>
document.addEventListener('keydown', function(e) {{ if (e.key === 'Enter') doSubmit(); }});
async function doSubmit() {{
  const token = document.getElementById('token').value;
  const pw1 = document.getElementById('pw1').value;
  const pw2 = document.getElementById('pw2').value;
  const btn = document.getElementById('submit');
  const msg = document.getElementById('msg');
  msg.className = 'msg';
  msg.style.display = 'none';
  if (!token) {{ msg.className = 'msg err'; msg.textContent = 'This reset link is invalid. Request a new one.'; return; }}
  if (pw1.length < 8) {{ msg.className = 'msg err'; msg.textContent = 'Password must be at least 8 characters.'; return; }}
  if (pw1 !== pw2) {{ msg.className = 'msg err'; msg.textContent = 'Passwords don\\'t match.'; return; }}
  btn.disabled = true;
  btn.textContent = 'Updating...';
  try {{
    const r = await fetch('/app/auth/reset-password', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{token: token, new_password: pw1}}),
    }});
    const d = await r.json();
    if (!r.ok) {{
      msg.className = 'msg err';
      msg.textContent = d.detail || 'Could not reset password. Request a new reset link.';
      btn.disabled = false;
      btn.textContent = 'Update password →';
      return;
    }}
    msg.className = 'msg ok';
    msg.textContent = 'Password updated. Redirecting to sign in...';
    btn.textContent = '✓ Updated';
    setTimeout(function() {{ window.location.href = '/app'; }}, 1500);
  }} catch(e) {{
    msg.className = 'msg err';
    msg.textContent = 'Something went wrong. Please try again.';
    btn.disabled = false;
    btn.textContent = 'Update password →';
  }}
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.post("/api/admin/generate-reset-link")
async def generate_reset_link_admin(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Super-admin only: generate a password reset link for any operator and
    return the raw URL. Used when SendGrid isn't configured, or to help
    an operator who can't receive email. The link works exactly like a
    normal forgot-password link — single-use, 1-hour expiry.

    Body: {"email": "operator@example.com"}
    Returns: {"ok": true, "reset_url": "https://.../app/reset-password?token=...", "expires_at": "..."}

    Deliberately bypasses rate limits (admin action) and the
    email-enumeration safeguard (admin needs to know if email is wrong).
    """
    _require_super_admin(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email is required")

    from sqlalchemy import text as _text
    row = (await db.execute(
        _text("""
            SELECT id, email, owner_name
            FROM operator_accounts
            WHERE email = :e
            LIMIT 1
        """),
        {"e": email},
    )).fetchone()

    if not row:
        raise HTTPException(404, f"No operator account found for {email}")

    # Invalidate any prior unused tokens for this operator
    await db.execute(
        _text("UPDATE password_reset_tokens SET used_at = NOW() WHERE operator_id = :oid AND used_at IS NULL"),
        {"oid": str(row.id)},
    )

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(seconds=_RESET_TOKEN_TTL_SECONDS)

    admin_email = ""
    try:
        user = _get_current_user(request)
        if user:
            admin_email = user.get("email", "")
    except Exception:
        pass

    await db.execute(
        _text("""
            INSERT INTO password_reset_tokens
                (operator_id, token_hash, expires_at, ip_address, user_agent)
            VALUES (:oid, :hash, :exp, :ip, :ua)
        """),
        {
            "oid":   str(row.id),
            "hash":  token_hash,
            "exp":   expires_at,
            "ip":    f"admin:{admin_email}",
            "ua":    f"admin-generate-reset-link by {admin_email}",
        },
    )
    await db.commit()

    base_url = os.getenv("BASE_URL", "https://oyvoda.com")
    reset_url = f"{base_url}/app/reset-password?token={raw_token}"

    logger.warning(
        "[PasswordReset] ADMIN generated reset link for operator=%s email=%s admin=%s",
        row.id, email, admin_email,
    )

    return {
        "ok": True,
        "operator_id": str(row.id),
        "operator_email": row.email,
        "operator_name": row.owner_name or "",
        "reset_url": reset_url,
        "expires_at": expires_at.isoformat(),
        "note": "Share this link with the operator. It's single-use and expires in 1 hour.",
    }


@router.get("/auth/session")
async def auth_session(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Return the effective current operator session for the dashboard shell."""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    operator = await _build_session_operator(db, user)
    return {"ok": True, "operator": operator}


# ─── LOGIN PAGE ──────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign In — Oyvoda</title>
<meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
.login-wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px;position:relative}
.login-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(200,120,50,0.025) 1px,transparent 1px),linear-gradient(90deg,rgba(200,120,50,0.025) 1px,transparent 1px);background-size:60px 60px;pointer-events:none}
.login-glow{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:500px;height:400px;background:radial-gradient(ellipse,rgba(200,120,50,0.06) 0%,transparent 70%);pointer-events:none}
.login-card{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.15);border-radius:20px;padding:48px;width:100%;max-width:440px;position:relative;z-index:1;box-shadow:0 32px 80px rgba(0,0,0,0.5)}
.login-logo{font-family:'Cormorant Garamond',serif;font-size:28px;font-weight:500;color:#f0ebe3;letter-spacing:-0.02em;margin-bottom:8px;display:block;text-decoration:none}
.login-sub{font-size:13px;color:rgba(240,235,227,0.4);margin-bottom:36px;font-weight:300}
.form-group{margin-bottom:20px}
.form-label{display:block;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.4);margin-bottom:8px}
.form-input{width:100%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px 16px;font-size:14px;color:#f0ebe3;font-family:'DM Sans',sans-serif;transition:all 0.15s;outline:none}
.form-input:focus{border-color:rgba(200,120,50,0.4);background:rgba(255,255,255,0.06)}
.form-input::placeholder{color:rgba(240,235,227,0.2)}
.btn-login{width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;padding:14px;font-size:14px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:8px;transition:all 0.15s}
.btn-login:hover{background:#e09040;transform:translateY(-1px)}
.btn-login:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.login-error{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;padding:12px 14px;font-size:13px;color:#ef4444;margin-bottom:20px;display:none}
.login-divider{border:none;border-top:1px solid rgba(255,255,255,0.06);margin:24px 0}
.login-footer-links{display:flex;justify-content:space-between;font-size:12px;color:rgba(240,235,227,0.3)}
.login-footer-links a{color:rgba(240,235,227,0.3);text-decoration:none;transition:color 0.15s}
.login-footer-links a:hover{color:rgba(240,235,227,0.7)}
.demo-hint{background:rgba(200,120,50,0.06);border:1px solid rgba(200,120,50,0.15);border-radius:8px;padding:12px 14px;font-size:12px;color:rgba(240,235,227,0.5);margin-bottom:20px;font-family:'DM Mono',monospace;line-height:1.6}
.demo-hint strong{color:#c87832}
footer.login-page-footer{padding:20px 48px;border-top:1px solid rgba(255,255,255,0.04);display:flex;justify-content:space-between;align-items:center}
footer.login-page-footer a{font-size:12px;color:rgba(240,235,227,0.2);text-decoration:none}
footer.login-page-footer a:hover{color:rgba(240,235,227,0.5)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin 0.6s linear infinite;margin-right:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="login-wrap">
  <div class="login-grid"></div>
  <div class="login-glow"></div>

  <div class="login-card">
    <a href="/" class="login-logo" style="display:block;text-align:center">oyvoda</a>
    <div class="login-sub" style="text-align:center">Operator dashboard — sign in to continue</div>

    <div class="login-error" id="login-error"></div>

    <div class="form-group">
      <label class="form-label">Email address</label>
      <input class="form-input" id="email" type="email" placeholder="you@example.com" autocomplete="email">
    </div>

    <div class="form-group">
      <label class="form-label">Password</label>
      <input class="form-input" id="password" type="password" placeholder="••••••••" autocomplete="current-password">
    </div>

    <button class="btn-login" id="login-btn" onclick="doLogin()">Sign In →</button>

    <hr class="login-divider">

    <div class="login-footer-links">
      <a href="mailto:info@oyvoda.com">Request access</a>
      <a href="/app/forgot-password">Forgot password?</a>
    </div>
  </div>
</div>

<footer class="login-page-footer">
  <a href="/">← oyvoda.com</a>
  <div style="display:flex;gap:24px">
    <a href="/security">Security</a>
    <a href="/privacy">Privacy</a>
  </div>
</footer>

<script>
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') doLogin();
});

async function doLogin() {
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const btn = document.getElementById('login-btn');
  const err = document.getElementById('login-error');

  if (!email || !password) {
    showError('Please enter your email and password.');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Signing in...';
  err.style.display = 'none';

  try {
    const res = await fetch('/app/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email, password})
    });
    const data = await res.json();

    if (!res.ok) {
      showError(data.detail || 'Invalid email or password.');
      btn.disabled = false;
      btn.innerHTML = 'Sign In →';
      return;
    }

    // Store operator info for the app shell
    sessionStorage.setItem('oyvoda_op', JSON.stringify(data.operator));
    window.location.href = '/app/dashboard';
  } catch(e) {
    showError('Connection error. Please try again.');
    btn.disabled = false;
    btn.innerHTML = 'Sign In →';
  }
}

function showError(msg) {
  const err = document.getElementById('login-error');
  err.textContent = msg;
  err.style.display = 'block';
}
</script>
</body>
</html>"""


# ─── MAIN APP SHELL ──────────────────────────────────────────────────────────

# Dashboard HTML shell — loaded from app/static/dashboard/index.html
# Edit that file directly. All dashboard sections live in app/static/dashboard/
# (index.html, styles/*.css, js/*.js, js/sections/*.js)
import pathlib as _pathlib
_SHELL_PATH = _pathlib.Path(__file__).parent.parent.parent.parent / "static" / "dashboard" / "index.html"
APP_HTML: str = _SHELL_PATH.read_text(encoding="utf-8")
_V2_DIST_DIR = _pathlib.Path(__file__).parent.parent.parent.parent / "static" / "dashboard-v2" / "dist"
_V2_INDEX_PATH = _V2_DIST_DIR / "index.html"
V2_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="noindex">
  <title>Oyvoda v2</title>
  <style>
    body{margin:0;font-family:Inter,system-ui,sans-serif;background:#fafbfc;color:#0f1419;display:flex;align-items:center;justify-content:center;min-height:100vh}
    .card{max-width:680px;padding:32px;border:1px solid #dde1e6;border-radius:20px;background:#fff;box-shadow:0 18px 50px rgba(15,20,25,.08)}
    .eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0f766e;margin:0 0 8px}
    h1{margin:0 0 12px;font-size:32px}
    p{margin:0;color:#4a5260;line-height:1.6}
    code{background:#f3f5f7;border-radius:8px;padding:2px 6px}
  </style>
</head>
<body>
  <main class="card">
    <p class="eyebrow">Ship S</p>
    <h1>Oyvoda v2 scaffold is mounted</h1>
    <p>The authenticated <code>/app/v2</code> route is live. Build the frontend bundle with <code>npm run build:dashboard-v2</code> to replace this fallback shell with the React app.</p>
  </main>
</body>
</html>"""


def _render_v2_shell() -> str:
    if _V2_INDEX_PATH.exists():
        return _V2_INDEX_PATH.read_text(encoding="utf-8")
    return V2_FALLBACK_HTML
# ─── ROUTES ──────────────────────────────────────────────────────────────────

# ─── SUPER ADMIN API ENDPOINTS ───────────────────────────────────────────────

def _require_super_admin(request: Request) -> dict:
    """Dependency — raises 403 if caller is not super_admin."""
    user = _get_current_user(request)
    if not user or user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return user


@router.get("/api/admin/operators")
async def list_all_operators_admin(request: Request):
    """
    Super admin only — list every operator from DB + env vars.
    """
    _require_super_admin(request)
    try:
        from app.core.database import get_db_session
        from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
        async with get_db_session() as db:
            db_operators = await _gas().list_all_operators(db)
    except Exception as e:
        db_operators = []

    # Also include legacy env var operators
    env_operators = []
    for _i in range(1, 6):
        _oe   = os.getenv(f"OPERATOR_{_i}_EMAIL", "").strip().lower()
        _oid  = os.getenv(f"OPERATOR_{_i}_ID", f"op_{_i:03d}")
        _name = os.getenv(f"OPERATOR_{_i}_NAME", "")
        _co   = os.getenv(f"OPERATOR_{_i}_COMPANY", "")
        if _oe and _name:
            # Don't duplicate DB operators
            if not any(o["email"] == _oe for o in db_operators):
                env_operators.append({
                    "id": _oid, "email": _oe, "name": _name,
                    "company": _co, "source": "env",
                    "tenant_id": _oid,
                })

    all_ops = db_operators + env_operators
    return {"operators": all_ops, "count": len(all_ops)}


@router.post("/api/admin/scope")
async def set_operator_scope(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Super admin only — switch which operator the admin is currently viewing.
    Issues a new access token scoped to that operator's tenant.

    POST body: {"operator_id": "00000000-0000-0000-0000-000000000001"}
    or         {"operator_id": null}  to return to platform-wide view
    """
    user = _require_super_admin(request)

    try:
        body = await request.json()
        target_op_id = body.get("operator_id")  # None = platform-wide
    except Exception:
        raise HTTPException(400, "Invalid request body")

    target_tenant_id = None
    operator_session = None
    if target_op_id:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT tenant_id FROM operator_accounts WHERE id = CAST(:id AS uuid) LIMIT 1"),
            {"id": target_op_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Operator not found")
        target_tenant_id = str(row.tenant_id)
        operator_session = await _build_session_operator(db, {
            "sub": user["sub"],
            "email": user["email"],
            "role": "super_admin",
            "scoped_op": target_op_id,
            "tid": target_tenant_id,
        })
    else:
        operator_session = await _build_session_operator(db, {
            "sub": user["sub"],
            "email": user["email"],
            "role": "super_admin",
        })

    # Issue new access token with scoped_op set
    new_access = _make_access_token(
        operator_id=user["sub"],
        email=user["email"],
        role="super_admin",
        tenant_id=target_tenant_id,
        scoped_operator_id=target_op_id,
    )
    new_refresh = _make_refresh_token(
        operator_id=user["sub"],
        email=user["email"],
        role="super_admin",
        tenant_id=target_tenant_id,
        scoped_operator_id=target_op_id,
    )
    secure_cookies = _should_use_secure_cookies(request)

    resp = JSONResponse({
        "ok": True,
        "scoped_to": target_op_id,
        "operator": operator_session,
        "message": f"Now viewing operator {target_op_id}" if target_op_id else "Platform-wide view",
    })
    resp.set_cookie(
        "oyvoda_access", new_access,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_ACCESS_TTL, path="/",
    )
    resp.set_cookie(
        "oyvoda_refresh", new_refresh,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_REFRESH_TTL, path="/app/auth",
    )
    if target_op_id and target_tenant_id:
        resp.set_cookie(
            "oyvoda_scoped_op", target_op_id,
            httponly=True, secure=secure_cookies,
            samesite="lax", max_age=_REFRESH_TTL, path="/",
        )
        resp.set_cookie(
            "oyvoda_scoped_tid", target_tenant_id,
            httponly=True, secure=secure_cookies,
            samesite="lax", max_age=_REFRESH_TTL, path="/",
        )
    else:
        resp.delete_cookie("oyvoda_scoped_op", path="/")
        resp.delete_cookie("oyvoda_scoped_tid", path="/")
    return resp


@router.get("/admin/scope/{operator_id}", include_in_schema=False)
async def set_operator_scope_via_redirect(
    operator_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Super admin only — scope into an operator using a normal browser navigation.

    This is more reliable than fetch() + manual redirect for admin support flows
    because the Set-Cookie headers and redirect happen in one server response.
    """
    user = _require_super_admin(request)

    from sqlalchemy import text
    result = await db.execute(
        text("SELECT tenant_id FROM operator_accounts WHERE id = CAST(:id AS uuid) LIMIT 1"),
        {"id": operator_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Operator not found")

    target_tenant_id = str(row.tenant_id)
    new_access = _make_access_token(
        operator_id=user["sub"],
        email=user["email"],
        role="super_admin",
        tenant_id=target_tenant_id,
        scoped_operator_id=operator_id,
    )
    new_refresh = _make_refresh_token(
        operator_id=user["sub"],
        email=user["email"],
        role="super_admin",
        tenant_id=target_tenant_id,
        scoped_operator_id=operator_id,
    )
    secure_cookies = _should_use_secure_cookies(request)

    resp = RedirectResponse("/app/dashboard", status_code=302)
    resp.set_cookie(
        "oyvoda_access", new_access,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_ACCESS_TTL, path="/",
    )
    resp.set_cookie(
        "oyvoda_refresh", new_refresh,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_REFRESH_TTL, path="/app/auth",
    )
    resp.set_cookie(
        "oyvoda_scoped_op", operator_id,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_REFRESH_TTL, path="/",
    )
    resp.set_cookie(
        "oyvoda_scoped_tid", target_tenant_id,
        httponly=True, secure=secure_cookies,
        samesite="lax", max_age=_REFRESH_TTL, path="/",
    )
    return resp


@router.get("/api/admin/platform-stats")
async def platform_stats(request: Request):
    """
    Super admin only — cross-platform stats across all operators.
    """
    _require_super_admin(request)

    try:
        from app.core.database import get_db_session
        from sqlalchemy import text
        async with get_db_session() as db:
            # Active sessions across ALL tenants
            sessions_result = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'active') AS active_sessions,
                    COUNT(*) FILTER (WHERE status = 'active'
                        AND check_in <= CURRENT_DATE
                        AND check_out >= CURRENT_DATE) AS in_stay_now,
                    COUNT(DISTINCT tenant_id) AS active_tenants,
                    COUNT(*) AS total_sessions
                FROM concierge_guest_sessions
                WHERE created_at >= NOW() - INTERVAL '30 days'
            """))
            s = sessions_result.fetchone()

            # Pre-booking drafts across all tenants
            inquiries_result = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
                    COUNT(*) FILTER (WHERE status = 'replied') AS replied,
                    COUNT(*) AS total
                FROM pre_booking_inquiries
                WHERE created_at >= NOW() - INTERVAL '30 days'
                  AND archived_at IS NULL
            """))
            inq = inquiries_result.fetchone()

            # Gmail polling stats
            gmail_result = await db.execute(text("""
                SELECT COUNT(*) AS processed
                FROM gmail_processed_messages
                WHERE processed_at >= NOW() - INTERVAL '24 hours'
            """))
            gm = gmail_result.fetchone()

        return {
            "sessions": {
                "active": s.active_sessions or 0,
                "in_stay_now": s.in_stay_now or 0,
                "active_tenants": s.active_tenants or 0,
                "total_30d": s.total_sessions or 0,
            },
            "pre_booking": {
                "pending_review": inq.pending or 0,
                "replied_30d": inq.replied or 0,
                "total_30d": inq.total or 0,
            },
            "gmail": {
                "processed_24h": gm.processed or 0,
            },
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "generated_at": datetime.utcnow().isoformat()}


@router.post("/api/admin/relink-default-tenant")
async def relink_default_tenant_admin(request: Request):
    """Super admin only — move imported default-tenant rows onto a real operator tenant."""
    _require_super_admin(request)
    try:
        body = await request.json()
        new_tenant_id = (body.get("tenant_id") or "").strip()
    except Exception:
        raise HTTPException(400, "Invalid request body")

    if not new_tenant_id:
        raise HTTPException(400, "tenant_id is required")

    import asyncio

    def _relink():
        from app.api.v1.endpoints.admin_seed import _get_sync_conn

        conn = _get_sync_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE properties SET tenant_id=%s, updated_at=NOW() WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_IMPORT_TENANT_ID),
            )
            props = cur.rowcount
            cur.execute(
                "UPDATE concierge_scoped_knowledge SET tenant_id=%s, updated_at=NOW() WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_IMPORT_TENANT_ID),
            )
            knowledge = cur.rowcount
            cur.execute(
                "UPDATE concierge_scoped_knowledge_history SET tenant_id=%s WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_IMPORT_TENANT_ID),
            )
            conn.commit()
            return {"properties_relinked": props, "knowledge_relinked": knowledge}
        finally:
            cur.close()
            conn.close()

    result = await asyncio.get_event_loop().run_in_executor(None, _relink)
    return {"ok": True, "tenant_id": new_tenant_id, **result}


@router.get("/admin/operators", response_class=HTMLResponse, include_in_schema=False)
async def operator_directory_admin(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Super-admin operator directory with tenant IDs and relink actions."""
    _require_super_admin(request)
    from sqlalchemy import text

    result = await db.execute(text("""
        SELECT
            a.id,
            a.tenant_id,
            a.email,
            a.owner_name,
            a.company_name,
            a.plan,
            a.onboarding_complete,
            a.created_at,
            COUNT(DISTINCT p.id) AS property_count,
            MAX(g.watched_email) AS gmail_inbox
        FROM operator_accounts a
        LEFT JOIN properties p ON p.tenant_id = a.tenant_id
        LEFT JOIN operator_gmail_creds g ON g.operator_id = a.id
        GROUP BY a.id, a.tenant_id, a.email, a.owner_name, a.company_name,
                 a.plan, a.onboarding_complete, a.created_at
        ORDER BY a.created_at DESC
    """))
    operators = [dict(r._mapping) for r in result.fetchall()]

    default_counts_result = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM properties WHERE tenant_id = :tid) AS properties_count,
            (
                SELECT COUNT(*)
                FROM concierge_scoped_knowledge
                WHERE tenant_id = :tid
                  AND COALESCE(is_active, TRUE) = TRUE
            ) AS knowledge_count
    """), {"tid": DEFAULT_IMPORT_TENANT_ID})
    default_counts = dict(default_counts_result.fetchone()._mapping)

    rows_html = ""
    for op in operators:
        tenant_id = str(op.get("tenant_id") or "")
        operator_id = str(op.get("id") or "")
        gmail = op.get("gmail_inbox") or "<span style='color:#f59e0b'>Not connected</span>"
        onboarded = "Yes" if op.get("onboarding_complete") else "No"
        created = str(op.get("created_at") or "")[:10]
        rows_html += f"""
        <tr>
          <td style='padding:12px 16px'>
            <div style='font-weight:600'>{op.get("owner_name","")}</div>
            <div style='font-size:12px;color:rgba(240,235,227,0.45)'>{op.get("company_name","")}</div>
          </td>
          <td style='padding:12px 16px;font-size:12px'>{op.get("email","")}</td>
          <td style='padding:12px 16px'><code style='font-size:11px;background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;color:#c87832'>{operator_id}</code></td>
          <td style='padding:12px 16px'><code style='font-size:11px;background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;color:#c87832'>{tenant_id}</code></td>
          <td style='padding:12px 16px;text-align:center'>{op.get("property_count", 0)}</td>
          <td style='padding:12px 16px;font-size:12px'>{gmail}</td>
          <td style='padding:12px 16px;font-size:12px'>active</td>
          <td style='padding:12px 16px;font-size:12px'>{onboarded}</td>
          <td style='padding:12px 16px;font-size:12px;color:rgba(240,235,227,0.45)'>{created}</td>
          <td style='padding:12px 16px;text-align:right'>
            <button onclick="copyTenant('{tenant_id}')" style='margin-right:6px;font-size:11px;background:rgba(200,120,50,0.15);border:1px solid rgba(200,120,50,0.35);color:#c87832;border-radius:6px;padding:6px 10px;cursor:pointer'>Copy Tenant</button>
            <button onclick="viewAsOperator('{operator_id}', this)" style='margin-right:6px;font-size:11px;background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.35);color:#93c5fd;border-radius:6px;padding:6px 10px;cursor:pointer'>View as Operator</button>
            <button onclick="relinkTenant('{tenant_id}', this)" style='font-size:11px;background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.35);color:#22c55e;border-radius:6px;padding:6px 10px;cursor:pointer'>Relink Import</button>
          </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width,initial-scale=1.0'>
<title>Operator Directory — Oyvoda</title>
<link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap' rel='stylesheet'>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;padding:32px}}
.header{{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:28px}}
.logo{{font-family:'Cormorant Garamond',serif;font-size:24px;color:#f0ebe3;text-decoration:none}}
.sub{{font-size:13px;color:rgba(240,235,227,0.5);margin-top:6px;max-width:760px;line-height:1.6}}
.actions{{display:flex;gap:10px;flex-wrap:wrap}}
.btn{{display:inline-flex;align-items:center;justify-content:center;background:#c87832;color:#fff;border:none;border-radius:10px;padding:11px 14px;font-size:13px;font-weight:600;text-decoration:none;cursor:pointer}}
.btn-sec{{display:inline-flex;align-items:center;justify-content:center;background:transparent;color:rgba(240,235,227,0.6);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:11px 14px;font-size:13px;text-decoration:none}}
.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:24px}}
.card{{background:rgba(13,18,32,0.82);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:18px}}
.stat-val{{font-size:28px;font-weight:600;color:#c87832}}
.stat-label{{font-size:12px;color:rgba(240,235,227,0.45);margin-top:4px}}
.banner{{background:rgba(200,120,50,0.08);border:1px solid rgba(200,120,50,0.18);border-radius:14px;padding:16px 18px;margin-bottom:20px;line-height:1.6}}
table{{width:100%;border-collapse:collapse;background:rgba(13,18,32,0.82);border:1px solid rgba(255,255,255,0.08);border-radius:14px;overflow:hidden}}
th{{padding:12px 16px;text-align:left;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(240,235,227,0.4);font-family:'DM Mono',monospace;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.07)}}
tr:not(:last-child){{border-bottom:1px solid rgba(255,255,255,0.05)}}
tr:hover{{background:rgba(255,255,255,0.02)}}
#toast{{position:fixed;bottom:24px;right:24px;background:#22c55e;color:#fff;border-radius:8px;padding:10px 18px;font-size:13px;display:none;z-index:999}}
@media (max-width: 1100px) {{
  .stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}
  body{{padding:20px}}
}}
</style>
</head>
<body>
  <div class='header'>
    <div>
      <a href='/app/dashboard' class='logo'>oyvoda</a>
      <div class='sub'>Operator directory for support and onboarding. Use this to find tenant IDs, confirm Gmail connection status, and relink imported Beach Habitats records without going back to Railway logs or Supabase.</div>
    </div>
    <div class='actions'>
      <a href='/app/dashboard' class='btn-sec'>Back to Dashboard</a>
    </div>
  </div>

  <div class='stats'>
    <div class='card'><div class='stat-val'>{len(operators)}</div><div class='stat-label'>Operators</div></div>
    <div class='card'><div class='stat-val'>{sum((op.get("property_count") or 0) for op in operators)}</div><div class='stat-label'>Linked Properties</div></div>
    <div class='card'><div class='stat-val'>{sum(1 for op in operators if op.get("gmail_inbox"))}</div><div class='stat-label'>Gmail Connected</div></div>
    <div class='card'><div class='stat-val'>{default_counts.get("properties_count", 0)}</div><div class='stat-label'>Default Import Properties</div></div>
  </div>

  <div class='banner'>
    Default import tenant <code style='color:#c87832'>{DEFAULT_IMPORT_TENANT_ID}</code> currently holds
    <strong>{default_counts.get("properties_count", 0)} properties</strong> and
    <strong>{default_counts.get("knowledge_count", 0)} knowledge rows</strong>.
    Clicking <strong>Relink Import</strong> moves those records onto the selected operator tenant.
  </div>

  <table>
    <thead>
      <tr>
        <th>Operator</th>
        <th>Login Email</th>
        <th>Operator ID</th>
        <th>Tenant ID</th>
        <th>Properties</th>
        <th>Gmail Inbox</th>
        <th>Status</th>
        <th>Onboarded</th>
        <th>Created</th>
        <th></th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>

  <div id='toast'></div>
  <script>
    function showToast(message, ok) {{
      const toast = document.getElementById('toast');
      toast.style.background = ok ? '#22c55e' : '#ef4444';
      toast.textContent = message;
      toast.style.display = 'block';
      setTimeout(function() {{ toast.style.display = 'none'; }}, 2500);
    }}

    async function copyTenant(tenantId) {{
      try {{
        await navigator.clipboard.writeText(tenantId);
        showToast('Tenant ID copied', true);
      }} catch (e) {{
        showToast('Could not copy tenant ID', false);
      }}
    }}

    async function relinkTenant(tenantId, btn) {{
      if (!confirm('Relink imported default-tenant records to this operator?')) return;
      const original = btn.textContent;
      btn.textContent = 'Relinking...';
      btn.disabled = true;
      try {{
        const r = await fetch('/app/api/admin/relink-default-tenant', {{
          method: 'POST',
          headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{tenant_id: tenantId}})
        }});
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.detail || d.error || 'Relink failed');
        showToast('Relinked ' + (d.properties_relinked || 0) + ' properties and ' + (d.knowledge_relinked || 0) + ' knowledge rows', true);
        setTimeout(function() {{ location.reload(); }}, 1200);
      }} catch (e) {{
        showToast(e.message || 'Relink failed', false);
        btn.textContent = original;
        btn.disabled = false;
      }}
    }}

    function viewAsOperator(operatorId, btn) {{
      btn.textContent = 'Opening...';
      btn.disabled = true;
      window.location.href = '/app/admin/scope/' + encodeURIComponent(operatorId);
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)

# ─── TEAM MANAGEMENT API ──────────────────────────────────────────────────────────────────

async def _get_operator_context(request: Request, db: AsyncSession) -> dict:
    """
    Extract operator_id and tenant_id from the current JWT.

    operator_id  = the row `id` from operator_accounts (used as FK in team tables)
    tenant_id    = the `tenant_id` UUID from operator_accounts (used to scope all
                   concierge / knowledge / session data)

    Both are stored in the JWT at login time (`sub` and `tid` respectively).
    For backwards-compat with tokens issued before `tid` was added, tenant_id
    falls back to operator_id so existing sessions don’t break.
    """
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("role") == "super_admin":
        scoped_operator_id = user.get("scoped_op")
        tenant_id = user.get("tid")
        if not scoped_operator_id or not tenant_id:
            raise HTTPException(403, "Use operator-specific endpoints as a scoped operator")
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT id, tenant_id, email
            FROM operator_accounts
            WHERE id = CAST(:id AS uuid)
            LIMIT 1
        """), {"id": scoped_operator_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Scoped operator not found")
        return {
            "operator_id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "role": "owner",
            "email": row.email or "",
            "impersonating": True,
            "admin_email": user.get("email", ""),
        }
    operator_id = user.get("sub")
    # `tid` is set at login for DB-backed operators; fall back to operator_id
    # for legacy tokens or env-var operators where operator_id == tenant root.
    tenant_id = user.get("tid") or operator_id
    return {
        "operator_id": operator_id,
        "tenant_id":   tenant_id,
        "role":        user.get("role", "owner"),
        "email":       user.get("email", ""),
    }


@router.get("/api/properties")
async def get_properties(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List all properties for the current operator tenant."""
    import uuid as _uuid
    from datetime import datetime as _dt
    from sqlalchemy import text as _text

    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    try:
        # Resolve tenant_id — works for both regular operators and super-admins
        tenant_id = user.get("tid")
        if not tenant_id:
            op_row = await db.execute(_text(
                "SELECT tenant_id FROM operator_accounts WHERE id = CAST(:oid AS uuid) LIMIT 1"
            ), {"oid": user.get("sub", "")})
            row = op_row.fetchone()
            if row:
                tenant_id = str(row[0])
        if not tenant_id:
            raise HTTPException(403, "No tenant context — complete onboarding first")

        result = await db.execute(_text("""
            SELECT
                id, property_code, external_id,
                address_street, address_city, address_state, address_zip,
                community, bedrooms, bathrooms, sleeps, property_type,
                has_pool, has_hot_tub, pets_allowed, data_source, created_at
            FROM properties
            WHERE tenant_id = CAST(:tid AS uuid)
              AND COALESCE(is_active, TRUE) = TRUE
            ORDER BY address_street ASC
        """), {"tid": tenant_id})

        cleaned = []
        for r in result.fetchall():
            clean = {}
            for k, v in dict(r._mapping).items():
                if isinstance(v, _uuid.UUID):
                    clean[k] = str(v)
                elif isinstance(v, _dt):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = v
            cleaned.append(clean)

        return {"properties": cleaned, "count": len(cleaned)}

    except HTTPException:
        raise
    except Exception as _e:
        import logging as _log
        _log.getLogger(__name__).error("properties endpoint error: %s", _e, exc_info=True)
        raise HTTPException(500, f"Properties query failed: {type(_e).__name__}: {_e}")


@router.post("/api/properties/import")
async def import_properties_upload(
    request: Request,
    file: UploadFile = File(...),
    source_label: str = Form("dashboard_upload"),
    db: AsyncSession = Depends(get_async_session),
):
    """Import an operator-uploaded property table into the canonical property store."""
    import uuid as _uuid
    from sqlalchemy import text as _text

    from app.services.property_import_service import PropertyImportService
    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    tenant_id = str(ctx["tenant_id"])
    filename = file.filename or "properties-upload"
    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    rows = _records_from_uploaded_property_file(filename, content)
    if not rows:
        raise HTTPException(400, "No property rows found in uploaded file")

    property_cols = await _table_columns(db, "properties")
    market_id = None
    if "market_id" in property_cols:
        order_col = "created_at" if "created_at" in property_cols else "property_code"
        market_row = (
            await db.execute(
                _text(
                    f"""
                    SELECT market_id
                    FROM properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND COALESCE(is_active, TRUE) = TRUE
                      AND market_id IS NOT NULL
                    ORDER BY {order_col} DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).fetchone()
        market_id = str(market_row[0]) if market_row and market_row[0] else None

    svc = PropertyImportService(db)
    result = await svc.import_from_tabular_rows(
        operator_id=tenant_id,
        company_id=tenant_id,
        market_id=market_id,
        rows=rows,
        source_label=source_label or "dashboard_upload",
    )
    await get_canonical_property_write_service(db).sync_tenant_sources(_uuid.UUID(tenant_id))

    return {
        "ok": True,
        "filename": filename,
        "source_label": source_label or "dashboard_upload",
        "rows_received": len(rows),
        "inserted": result.inserted,
        "updated": result.updated,
        "vector_indexed": result.vector_indexed,
        "warnings": result.warnings,
        "errors": result.errors,
        "property_ids": result.property_ids,
        "ingest_event_id": result.ingest_event_id,
        "observed_columns": result.observed_columns,
        "unmapped_columns": result.unmapped_columns,
        "rows_with_unmapped_fields": result.rows_with_unmapped_fields,
        "preserved_field_count": result.preserved_field_count,
        "mapping_profiles_used": result.mapping_profiles_used,
        "count": result.total,
        "success": result.success,
    }


@router.get("/api/properties/import-profiles")
async def get_property_import_profiles(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Return operator-configurable property import mapping profiles."""
    from sqlalchemy import text as _text

    ctx = await _get_operator_context(request, db)
    row = (
        await db.execute(
            _text(
                """
                SELECT extra
                FROM operator_settings
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
                """
            ),
            {"tid": str(ctx["tenant_id"])},
        )
    ).mappings().first()
    extra = row.get("extra") if row else {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    extra = extra if isinstance(extra, dict) else {}
    profiles = extra.get("property_import_profiles") or {}
    return {"profiles": profiles if isinstance(profiles, dict) else {}}


@router.patch("/api/properties/import-profiles")
async def update_property_import_profiles(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Update operator-configurable property import mapping profiles."""
    from sqlalchemy import text as _text

    ctx = await _get_operator_context(request, db)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")

    incoming = body.get("profiles")
    if not isinstance(incoming, dict):
        raise HTTPException(400, "`profiles` must be an object")

    sanitized_profiles: dict[str, dict[str, list[str]]] = {}
    for profile_name, field_map in incoming.items():
        normalized_profile = re.sub(r"[^a-z0-9]+", "_", str(profile_name or "").strip().lower()).strip("_")
        if not normalized_profile or not isinstance(field_map, dict):
            continue
        sanitized_field_map: dict[str, list[str]] = {}
        for field_name, aliases in field_map.items():
            normalized_field = re.sub(r"[^a-z0-9]+", "_", str(field_name or "").strip().lower()).strip("_")
            if not normalized_field:
                continue
            values = aliases if isinstance(aliases, list) else [aliases]
            cleaned_aliases: list[str] = []
            for alias in values:
                normalized_alias = re.sub(r"[^a-z0-9]+", "_", str(alias or "").strip().lower()).strip("_")
                if normalized_alias and normalized_alias not in cleaned_aliases:
                    cleaned_aliases.append(normalized_alias)
            if cleaned_aliases:
                sanitized_field_map[normalized_field] = cleaned_aliases
        if sanitized_field_map:
            sanitized_profiles[normalized_profile] = sanitized_field_map

    existing = (
        await db.execute(
            _text("SELECT 1 FROM operator_settings WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": str(ctx["tenant_id"])},
        )
    ).fetchone()
    existing_row = (
        await db.execute(
            _text("SELECT extra FROM operator_settings WHERE tenant_id = CAST(:tid AS uuid) LIMIT 1"),
            {"tid": str(ctx["tenant_id"])},
        )
    ).mappings().first()
    current_extra = existing_row.get("extra") if existing_row else {}
    if isinstance(current_extra, str):
        try:
            current_extra = json.loads(current_extra)
        except Exception:
            current_extra = {}
    current_extra = current_extra if isinstance(current_extra, dict) else {}
    current_extra["property_import_profiles"] = sanitized_profiles

    if existing:
        await db.execute(
            _text(
                """
                UPDATE operator_settings
                SET extra = CAST(:extra_json AS jsonb)
                WHERE tenant_id = CAST(:tid AS uuid)
                """
            ),
            {"tid": str(ctx["tenant_id"]), "extra_json": json.dumps(current_extra)},
        )
    else:
        await db.execute(
            _text(
                """
                INSERT INTO operator_settings (
                    tenant_id, operator_id,
                    prebooking_autosend_threshold, escalation_urgency_threshold,
                    kb_gap_detection_threshold, ai_concierge_name,
                    notify_emergency, notify_maintenance, notify_prebooking,
                    notify_kb_gaps, notify_weekly_analytics,
                    kb_suppressed_categories, ai_paused, extra
                ) VALUES (
                    CAST(:tid AS uuid), CAST(:oid AS uuid),
                    80, 85, 75, 'Oyvoda',
                    TRUE, TRUE, TRUE,
                    TRUE, TRUE,
                    '[]'::jsonb, FALSE, CAST(:extra_json AS jsonb)
                )
                """
            ),
            {
                "tid": str(ctx["tenant_id"]),
                "oid": str(ctx["operator_id"]),
                "extra_json": json.dumps(current_extra),
            },
        )
    await db.commit()
    return {"ok": True, "profiles": sanitized_profiles}


@router.post("/api/properties/ingest-events/{ingest_event_id}/replay")
async def replay_property_ingest_event(
    ingest_event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Replay a prior property ingest event through the canonical import path."""
    import uuid as _uuid
    from sqlalchemy import text as _text

    from app.services.property_import_service import PropertyImportService
    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    tenant_id = str(ctx["tenant_id"])

    property_cols = await _table_columns(db, "properties")
    market_id = None
    if "market_id" in property_cols:
        order_col = "created_at" if "created_at" in property_cols else "property_code"
        market_row = (
            await db.execute(
                _text(
                    f"""
                    SELECT market_id
                    FROM properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND COALESCE(is_active, TRUE) = TRUE
                      AND market_id IS NOT NULL
                    ORDER BY {order_col} DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).fetchone()
        market_id = str(market_row[0]) if market_row and market_row[0] else None

    svc = PropertyImportService(db)
    try:
        result = await svc.replay_ingest_event(
            ingest_event_id=ingest_event_id,
            operator_id=tenant_id,
            company_id=tenant_id,
            market_id=market_id,
        )
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 400, str(exc))

    await get_canonical_property_write_service(db).sync_tenant_sources(_uuid.UUID(tenant_id))

    return {
        "ok": True,
        "replayed_from_ingest_event_id": ingest_event_id,
        "new_ingest_event_id": result.ingest_event_id,
        "inserted": result.inserted,
        "updated": result.updated,
        "vector_indexed": result.vector_indexed,
        "warnings": result.warnings,
        "errors": result.errors,
        "observed_columns": result.observed_columns,
        "unmapped_columns": result.unmapped_columns,
        "rows_with_unmapped_fields": result.rows_with_unmapped_fields,
        "preserved_field_count": result.preserved_field_count,
        "mapping_profiles_used": result.mapping_profiles_used,
        "count": result.total,
        "success": result.success,
    }


@router.post("/api/properties/documents/import")
async def import_property_document_upload(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    target: str = Form("knowledge"),
    scope: str = Form("property"),
    property_code: Optional[str] = Form(None),
    asset_type: Optional[str] = Form(None),
    asset_name: Optional[str] = Form(None),
    source_label: str = Form("document_upload"),
    db: AsyncSession = Depends(get_async_session),
):
    """Import a property or portfolio document into KB, assets, or both."""
    from app.services.documents import extract_document
    from app.services.documents.normalization import get_pipeline
    from app.services.extraction import get_extraction_staging_service

    ctx = await _get_operator_context(request, db)
    tenant_id = str(ctx["tenant_id"])
    uploaded_by = str(ctx.get("email") or ctx.get("operator_id") or "")
    reviewer_id = str(ctx.get("operator_id") or ctx["tenant_id"])
    filename = file.filename or "document-upload"
    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    content_hash = hashlib.sha256(content).hexdigest()

    scope_value = (scope or "property").strip().lower()
    if scope_value not in {"property", "portfolio"}:
        raise HTTPException(400, "scope must be 'property' or 'portfolio'")

    target_value = (target or "knowledge").strip().lower()
    if target_value not in {"knowledge", "asset", "both"}:
        raise HTTPException(400, "target must be 'knowledge', 'asset', or 'both'")

    property_code_value = (property_code or "").strip() or None
    property_row = None
    if scope_value == "property" and not property_code_value:
        raise HTTPException(400, "property_code is required for property-scoped imports")
    if target_value in {"asset", "both"} and not property_code_value:
        raise HTTPException(400, "property_code is required for asset imports")
    if property_code_value:
        property_row = await _load_property_record_for_code(db, tenant_id, property_code_value)
        if not property_row:
            raise HTTPException(404, "Property code not found for this operator")

    document_row, stored_new_object, reused_existing = await _persist_source_document(
        db,
        tenant_id=tenant_id,
        property_id=str(property_row.get("property_id")) if property_row and property_row.get("property_id") else None,
        scope=scope_value,
        document_type=document_type,
        filename=filename,
        content=content,
        content_type=file.content_type,
        upload_method="operator_upload",
        uploaded_by=uploaded_by,
        content_hash=content_hash,
    )

    pipeline = get_pipeline()
    try:
        processed = pipeline.process(
            content,
            filename=filename,
            document_type_hint=_normalize_document_ingest_hint(document_type),
            content_type=file.content_type,
        )
        normalized = processed["normalized"]
        document_class = str(getattr(processed["document_class"], "value", processed["document_class"]))
        extraction = extract_document(
            getattr(normalized, "raw_text", "") or "",
            document_class,
            metadata={
                "filename": filename,
                "structured_rows": getattr(normalized, "structured_rows", None),
                "json_payload": getattr(normalized, "json_payload", None),
            },
        )
    except Exception as exc:
        document_row.extraction_status = "failed"
        document_row.extraction_error = str(exc)
        document_row.processed_at = datetime.now(timezone.utc)
        await db.commit()
        raise

    await _save_document_extraction(db, document_row=document_row, extraction=extraction)

    scope_type, scope_target_id = _document_scope_binding(
        tenant_id=tenant_id,
        scope=scope_value,
        property_row=property_row,
    )
    source_type = _document_source_type(filename)
    staging_service = get_extraction_staging_service()
    created_candidates: list[Any] = []
    auto_promote_results: list[Any] = []
    staged_candidates: list[Any] = []
    knowledge_result = None
    guest_qa_result = None
    asset_result = None
    if target_value in {"knowledge", "both"}:
        fact_payloads = _build_fact_candidate_payloads(
            extracted_fields=extraction.fields,
            source_type=source_type,
            source_document_id=str(document_row.id),
            source_label=source_label or "document_upload",
            document_type=document_type,
            document_class=document_class,
        )
        for payload in fact_payloads:
            created_candidates.append(
                await staging_service.create_candidate(
                    db,
                    tenant_id=tenant_id,
                    scope_type=scope_type,
                    scope_target_id=scope_target_id,
                    **payload,
                )
            )
        if created_candidates:
            auto_result = await staging_service.auto_promote_eligible(
                db,
                tenant_id,
                reviewed_by_user_id=reviewer_id,
                candidate_ids=[candidate.candidate_id for candidate in created_candidates],
            )
            auto_promote_results.extend(list(auto_result.get("results") or []))
            promoted_candidate_ids = {result.candidate_id for result in auto_promote_results}
            staged_candidates.extend(
                [candidate for candidate in created_candidates if candidate.candidate_id not in promoted_candidate_ids]
            )
        knowledge_promotions = [
            result for result in auto_promote_results
            if str(result.promoted_to_table or "") == "concierge_scoped_knowledge"
        ]
        knowledge_result = {
            "updated": bool(fact_payloads),
            "scope": scope_value,
            "property_external_id": "__all_properties__" if scope_value == "portfolio" else property_code_value,
            "auto_promoted_count": len(knowledge_promotions),
            "staged_for_review_count": len(
                [candidate for candidate in staged_candidates if candidate.candidate_type == "fact"]
            ),
        }
        if document_class == "guest_qa":
            guest_qa_result = await _import_guest_qa_records(
                db,
                tenant_id=tenant_id,
                reviewer_id=reviewer_id,
                scope_type=scope_type,
                scope_target_id=scope_target_id,
                filename=filename,
                extracted_fields=extraction.fields,
            )
    if target_value in {"asset", "both"} and property_code_value:
        asset_candidate = await staging_service.create_candidate(
            db,
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_target_id=scope_target_id,
            **_build_asset_candidate_payload(
                document_type=document_type,
                filename=filename,
                normalized=normalized,
                extracted_fields=extraction.fields,
                asset_type=asset_type,
                asset_name=asset_name,
                source_document_id=str(document_row.id),
                source_type=source_type,
            ),
        )
        created_candidates.append(asset_candidate)
        auto_result = await staging_service.auto_promote_eligible(
            db,
            tenant_id,
            reviewed_by_user_id=reviewer_id,
            candidate_ids=[asset_candidate.candidate_id],
        )
        asset_promotions = list(auto_result.get("results") or [])
        auto_promote_results.extend(asset_promotions)
        if not asset_promotions:
            staged_candidates.append(asset_candidate)
        promoted_asset = next(
            (
                result for result in asset_promotions
                if str(result.promoted_to_table or "") == "operator_property_assets"
            ),
            None,
        )
        asset_result = {
            "asset_id": str(promoted_asset.promoted_to_id) if promoted_asset and promoted_asset.promoted_to_id else "",
            "auto_promoted": bool(promoted_asset),
            "staged_for_review": not bool(promoted_asset),
        }

    await db.commit()

    auto_promoted_candidate_ids = [str(result.candidate_id) for result in auto_promote_results]
    auto_promoted_entry_ids = [
        str(result.promoted_to_id)
        for result in auto_promote_results
        if result.promoted_to_id is not None
    ]
    staged_candidate_ids = [str(candidate.candidate_id) for candidate in staged_candidates]

    return {
        "ok": True,
        "document_id": str(document_row.id),
        "document_group_id": str(document_row.document_group_id),
        "document_version": int(document_row.version_number),
        "document_reused": reused_existing,
        "document_stored": stored_new_object or reused_existing,
        "storage_backend": document_row.storage_backend,
        "filename": filename,
        "document_type": document_type,
        "document_class": document_class,
        "classification_confidence": processed.get("classification_confidence"),
        "scope": scope_value,
        "target": target_value,
        "property_code": property_code_value,
        "fields_extracted": len(extraction.fields),
        "extraction_candidates_created": len(created_candidates),
        "auto_promoted_count": len(auto_promote_results),
        "auto_promoted_candidate_ids": auto_promoted_candidate_ids,
        "auto_promoted_entry_ids": auto_promoted_entry_ids,
        "staged_for_review_count": len(staged_candidates),
        "staged_candidate_ids": staged_candidate_ids,
        "warnings": list(extraction.warnings or []) + list(extraction.errors or []),
        "knowledge_result": knowledge_result,
        "guest_qa_result": guest_qa_result,
        "asset_result": asset_result,
    }


@router.get("/api/property-links/suggest")
async def suggest_property_links(
    request: Request,
    query: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_async_session),
):
    """Suggest likely property matches for an unresolved alias or OTA property name."""
    import uuid as _uuid

    from app.services.property_canonical_service import get_canonical_property_service

    ctx = await _get_operator_context(request, db)
    try:
        matches = await get_canonical_property_service(db).suggest_property_matches(
            _uuid.UUID(str(ctx["tenant_id"])),
            query,
            limit=limit,
        )
        return {"query": query, "matches": matches, "count": len(matches)}
    except Exception as exc:
        logger.error("property-link suggest failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Property link suggestion failed: {type(exc).__name__}: {exc}")


@router.post("/api/property-links")
async def create_property_link(
    body: PropertyIdentityLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Persist a canonical alias or external-id mapping for a property."""
    import uuid as _uuid
    from sqlalchemy import text as _text

    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    tenant_id = _uuid.UUID(str(ctx["tenant_id"]))

    row = (
        await db.execute(
            _text(
                """
                SELECT property_code, external_id, address_street
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND property_code = :code
                LIMIT 1
                """
            ),
            {"tid": str(tenant_id), "code": body.canonical_property_code},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Property code not found for this operator")

    write_service = get_canonical_property_write_service(db)
    if body.display_name or body.marketing_name:
        await write_service.upsert_property_profile(
            tenant_id,
            canonical_property_code=body.canonical_property_code,
            display_name=body.display_name or body.property_name or row.get("address_street") or body.canonical_property_code,
            marketing_name=body.marketing_name or body.property_name or body.display_name,
            preferred_address=row.get("address_street") or "",
            source=body.source,
            metadata={"platform_listing_id": body.platform_listing_id or ""},
        )
    await write_service.link_property_identity(
        tenant_id,
        canonical_property_code=body.canonical_property_code,
        ref_value=body.ref_value,
        provider=body.provider,
        ref_kind=body.ref_kind,
        source=body.source,
        display_name=body.display_name,
        metadata={
            "property_name": body.property_name or "",
            "platform_listing_id": body.platform_listing_id or "",
        },
    )
    if body.platform_listing_id:
        await write_service.link_property_identity(
            tenant_id,
            canonical_property_code=body.canonical_property_code,
            ref_value=body.platform_listing_id,
            provider=(body.provider or "ota") if body.provider not in {"internal", ""} else "ota",
            ref_kind="external_id",
            source=body.source,
            metadata={"linked_from_ref_value": body.ref_value},
        )

    return {
        "ok": True,
        "canonical_property_code": body.canonical_property_code,
        "linked_ref": body.ref_value,
        "provider": body.provider,
        "ref_kind": body.ref_kind,
        "property": {
            "property_code": row.get("property_code") or "",
            "external_id": row.get("external_id") or "",
            "address_street": row.get("address_street") or "",
        },
    }


@router.patch("/api/properties/{property_code}/identity")
async def update_property_identity(
    property_code: str,
    body: PropertyProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Update the canonical display/marketing identity for a property without changing its code."""
    import uuid as _uuid
    from sqlalchemy import text as _text

    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    tenant_id = _uuid.UUID(str(ctx["tenant_id"]))

    row = (
        await db.execute(
            _text(
                """
                SELECT property_code, external_id, address_street
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND property_code = :code
                LIMIT 1
                """
            ),
            {"tid": str(tenant_id), "code": property_code},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Property code not found for this operator")

    write_service = get_canonical_property_write_service(db)
    await write_service.upsert_property_profile(
        tenant_id,
        canonical_property_code=property_code,
        display_name=body.display_name or property_code,
        marketing_name=body.marketing_name or body.display_name or "",
        preferred_address=body.preferred_address or row.get("address_street") or "",
        source=body.source,
        metadata={"external_id": row.get("external_id") or ""},
    )

    return {
        "ok": True,
        "property_code": property_code,
        "display_name": body.display_name or property_code,
        "marketing_name": body.marketing_name or body.display_name or "",
        "preferred_address": body.preferred_address or row.get("address_street") or "",
    }


@router.get("/api/property-links/reviews")
async def list_property_link_reviews(
    request: Request,
    status: str = Query("pending"),
    db: AsyncSession = Depends(get_async_session),
):
    """List property identity links that need operator review."""
    from sqlalchemy import text as _text

    ctx = await _get_operator_context(request, db)
    rows = (
        await db.execute(
            _text(
                """
                SELECT review_id, canonical_property_code, provider, ref_kind, ref_value,
                       platform_listing_id, platform_unit_id, property_name, display_name,
                       confidence, status, source, candidate_payload, metadata, created_at, updated_at
                FROM canonical_property_link_reviews
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND status = :status
                ORDER BY created_at DESC
                """
            ),
            {"tid": ctx["tenant_id"], "status": status},
        )
    ).mappings().all()
    cleaned = []
    for row in rows:
        cleaned.append({
            "review_id": int(row["review_id"]),
            "canonical_property_code": row["canonical_property_code"] or "",
            "provider": row["provider"] or "",
            "ref_kind": row["ref_kind"] or "",
            "ref_value": row["ref_value"] or "",
            "platform_listing_id": row["platform_listing_id"] or "",
            "platform_unit_id": row["platform_unit_id"] or "",
            "property_name": row["property_name"] or "",
            "display_name": row["display_name"] or "",
            "confidence": float(row["confidence"] or 0.0),
            "status": row["status"] or "",
            "source": row["source"] or "",
            "candidates": row["candidate_payload"] or [],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        })
    return {"reviews": cleaned, "count": len(cleaned)}


@router.post("/api/property-links/reviews/{review_id}/approve")
async def approve_property_link_review(
    review_id: int,
    body: PropertyLinkReviewDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Approve a pending property identity link review."""
    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    canonical_property_code = (body.canonical_property_code or "").strip()
    if not canonical_property_code:
        raise HTTPException(400, "canonical_property_code is required")

    await get_canonical_property_write_service(db).approve_property_link_review(
        UUID(str(ctx["tenant_id"])),
        review_id=review_id,
        canonical_property_code=canonical_property_code,
        approved_by=ctx.get("email") or ctx.get("operator_id") or "",
    )
    return {"ok": True, "review_id": review_id, "canonical_property_code": canonical_property_code}


@router.post("/api/property-links/reviews/{review_id}/reject")
async def reject_property_link_review(
    review_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Reject a pending property identity link review."""
    from app.services.property_canonical_write_service import get_canonical_property_write_service

    ctx = await _get_operator_context(request, db)
    await get_canonical_property_write_service(db).reject_property_link_review(
        UUID(str(ctx["tenant_id"])),
        review_id=review_id,
        rejected_by=ctx.get("email") or ctx.get("operator_id") or "",
    )
    return {"ok": True, "review_id": review_id}


@router.get("/api/properties/identity-report")
async def get_property_identity_report(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Summarize canonical property identity coverage for the current operator."""
    from collections import defaultdict
    from sqlalchemy import text as _text

    ctx = await _get_operator_context(request, db)
    tenant_id = str(ctx["tenant_id"])
    property_cols = await _table_columns(db, "properties")

    select_cols = [
        "property_code" if "property_code" in property_cols else "NULL::text AS property_code",
        "external_id" if "external_id" in property_cols else "NULL::text AS external_id",
        "address_street" if "address_street" in property_cols else "NULL::text AS address_street",
        "community" if "community" in property_cols else "NULL::text AS community",
        "data_source" if "data_source" in property_cols else "NULL::text AS data_source",
    ]
    properties = (
        await db.execute(
            _text(
                f"""
                SELECT {", ".join(select_cols)}
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND COALESCE(is_active, TRUE) = TRUE
                ORDER BY property_code NULLS LAST, address_street NULLS LAST
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()

    profile_rows = (
        await db.execute(
            _text(
                """
                SELECT canonical_property_code, display_name, marketing_name,
                       preferred_address, source, metadata, updated_at
                FROM canonical_property_profiles
                WHERE tenant_id = CAST(:tid AS uuid)
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    profiles_by_code = {str(row["canonical_property_code"] or ""): dict(row) for row in profile_rows}

    knowledge_by_code: dict[str, int] = defaultdict(int)
    all_properties_knowledge = 0
    knowledge_rows = (
        await db.execute(
            _text(
                """
                SELECT
                    k.scope_type,
                    p.property_code,
                    p.external_id,
                    COUNT(*) AS n
                FROM concierge_scoped_knowledge k
                LEFT JOIN properties p
                  ON k.scope_type = 'property'
                 AND p.id = k.scope_target_id
                 AND p.tenant_id = k.tenant_id
                WHERE k.tenant_id = CAST(:tid AS uuid)
                  AND COALESCE(k.is_active, TRUE) = TRUE
                  AND k.scope_type IN ('tenant', 'property')
                GROUP BY k.scope_type, p.property_code, p.external_id
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    for row in knowledge_rows:
        scope_type = str(row["scope_type"] or "")
        count = int(row["n"] or 0)
        if scope_type == "tenant":
            all_properties_knowledge = count
            continue
        code = str(row["property_code"] or row["external_id"] or "")
        if code:
            knowledge_by_code[code] = count

    ref_rows = (
        await db.execute(
            _text(
                """
                SELECT canonical_property_code, provider, ref_kind, ref_value, source, confidence
                FROM canonical_property_refs
                WHERE tenant_id = CAST(:tid AS uuid)
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    refs_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ref_rows:
        refs_by_code[str(row["canonical_property_code"] or "")].append(dict(row))

    review_rows = (
        await db.execute(
            _text(
                """
                SELECT canonical_property_code, status, COUNT(*) AS n
                FROM canonical_property_link_reviews
                WHERE tenant_id = CAST(:tid AS uuid)
                GROUP BY canonical_property_code, status
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    reviews_by_code: dict[str, dict[str, int]] = defaultdict(dict)
    pending_reviews = 0
    for row in review_rows:
        code = str(row["canonical_property_code"] or "")
        status = str(row["status"] or "")
        count = int(row["n"] or 0)
        reviews_by_code[code][status] = count
        if status == "pending":
            pending_reviews += count

    ingest_rows = []
    if await _table_columns(db, "property_ingest_events"):
        ingest_rows = (
            await db.execute(
                _text(
                    """
                    SELECT ingest_event_id, source_type, source_label, status, row_count,
                           inserted_count, updated_count, vector_indexed_count,
                           rows_with_unmapped_fields, preserved_field_count,
                           observed_columns, unmapped_columns, created_at
                    FROM property_ingest_events
                    WHERE tenant_id = CAST(:tid AS uuid)
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()

    assets_by_code: dict[str, int] = defaultdict(int)
    if await _table_columns(db, "operator_property_assets"):
        asset_rows = (
            await db.execute(
                _text(
                    """
                    SELECT property_code, COUNT(*) AS n
                    FROM operator_property_assets
                    WHERE tenant_id = CAST(:tid AS uuid)
                    GROUP BY property_code
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()
        for row in asset_rows:
            code = str(row["property_code"] or "")
            if code:
                assets_by_code[code] = int(row["n"] or 0)

    items = []
    with_display_name = 0
    with_marketing_name = 0
    with_pms_property_id = 0
    with_pms_unit_code = 0
    with_any_ota_id = 0
    with_alias = 0
    with_property_knowledge = 0
    with_asset_records = 0

    for row in properties:
        property_code = str(row.get("property_code") or "")
        profile = profiles_by_code.get(property_code, {})
        refs = refs_by_code.get(property_code, [])
        knowledge_count = int(knowledge_by_code.get(property_code, 0))
        asset_count = int(assets_by_code.get(property_code, 0))

        pms_property_ids = sorted(
            {str(ref.get("ref_value") or "") for ref in refs if ref.get("provider") == "pms" and ref.get("ref_kind") in {"property_id", "external_id"} and str(ref.get("ref_value") or "").strip()}
        )
        pms_unit_codes = sorted(
            {str(ref.get("ref_value") or "") for ref in refs if ref.get("provider") == "pms" and ref.get("ref_kind") in {"unit_code", "unit_id"} and str(ref.get("ref_value") or "").strip()}
        )
        aliases = sorted(
            {str(ref.get("ref_value") or "") for ref in refs if ref.get("ref_kind") == "alias" and str(ref.get("ref_value") or "").strip()}
        )
        ota_refs: dict[str, list[str]] = defaultdict(list)
        for ref in refs:
            provider = str(ref.get("provider") or "")
            ref_kind = str(ref.get("ref_kind") or "")
            ref_value = str(ref.get("ref_value") or "").strip()
            if provider in {"airbnb", "vrbo", "booking", "expedia", "ota"} and ref_value:
                ota_refs[provider].append(f"{ref_kind}:{ref_value}")
        ota_refs = {provider: sorted(set(values)) for provider, values in ota_refs.items() if values}

        display_name = str(profile.get("display_name") or "").strip()
        marketing_name = str(profile.get("marketing_name") or "").strip()
        preferred_address = str(profile.get("preferred_address") or row.get("address_street") or "").strip()

        if display_name:
            with_display_name += 1
        if marketing_name:
            with_marketing_name += 1
        if pms_property_ids:
            with_pms_property_id += 1
        if pms_unit_codes:
            with_pms_unit_code += 1
        if ota_refs:
            with_any_ota_id += 1
        if aliases:
            with_alias += 1
        if knowledge_count:
            with_property_knowledge += 1
        if asset_count:
            with_asset_records += 1

        items.append(
            {
                "property_code": property_code,
                "external_id": row.get("external_id") or "",
                "display_name": display_name,
                "marketing_name": marketing_name,
                "preferred_address": preferred_address,
                "address_street": row.get("address_street") or "",
                "community": row.get("community") or "",
                "data_source": row.get("data_source") or "",
                "profile_source": profile.get("source") or "",
                "profile_updated_at": profile.get("updated_at").isoformat() if profile.get("updated_at") else None,
                "pms_property_ids": pms_property_ids,
                "pms_unit_codes": pms_unit_codes,
                "ota_refs": ota_refs,
                "aliases": aliases,
                "knowledge_count": knowledge_count,
                "asset_count": asset_count,
                "review_status": reviews_by_code.get(property_code, {}),
            }
        )

    return {
        "summary": {
            "total_properties": len(items),
            "canonical_profiles": len(profile_rows),
            "canonical_refs": len(ref_rows),
            "pending_reviews": pending_reviews,
            "with_display_name": with_display_name,
            "with_marketing_name": with_marketing_name,
            "with_pms_property_id": with_pms_property_id,
            "with_pms_unit_code": with_pms_unit_code,
            "with_any_ota_id": with_any_ota_id,
            "with_alias": with_alias,
            "with_property_knowledge": with_property_knowledge,
            "with_asset_records": with_asset_records,
            "portfolio_knowledge_records": all_properties_knowledge,
            "recent_ingest_events": len(ingest_rows),
        },
        "properties": items,
        "recent_ingest_events": [
            {
                "ingest_event_id": str(row.get("ingest_event_id") or ""),
                "source_type": row.get("source_type") or "",
                "source_label": row.get("source_label") or "",
                "status": row.get("status") or "",
                "row_count": int(row.get("row_count") or 0),
                "inserted_count": int(row.get("inserted_count") or 0),
                "updated_count": int(row.get("updated_count") or 0),
                "vector_indexed_count": int(row.get("vector_indexed_count") or 0),
                "rows_with_unmapped_fields": int(row.get("rows_with_unmapped_fields") or 0),
                "preserved_field_count": int(row.get("preserved_field_count") or 0),
                "observed_columns": row.get("observed_columns") or [],
                "unmapped_columns": row.get("unmapped_columns") or [],
                "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
            }
            for row in ingest_rows
        ],
        "count": len(items),
    }


@router.get("/api/team")
async def get_team(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List all team members for the current operator."""
    ctx = await _get_operator_context(request, db)
    from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
    members = await _gas().list_team_members(db, ctx["operator_id"])
    return {"members": members, "count": len(members)}


@router.post("/api/team/invite")
async def invite_team_member(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Invite a new team member (owner/manager only)."""
    ctx = await _get_operator_context(request, db)
    if ctx["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Only owners and managers can invite team members")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")

    email = body.get("email", "").strip()
    name  = body.get("name", "").strip()
    role  = body.get("role", "staff")

    if not email or not name:
        raise HTTPException(400, "Email and name are required")
    if role not in ("manager", "staff"):
        raise HTTPException(400, "Role must be 'manager' or 'staff'")

    from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
    try:
        result = await _gas().invite_team_member(
            db, ctx["operator_id"], ctx["tenant_id"], email, name, role
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Send invite email if SendGrid configured
    _send_invite_email_bg(email, name, result["invite_url"], ctx.get("email", ""))

    return {"ok": True, "invite": result}


@router.delete("/api/team/{member_id}")
async def remove_team_member(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a team member (owner only)."""
    ctx = await _get_operator_context(request, db)
    if ctx["role"] != "owner":
        raise HTTPException(403, "Only owners can remove team members")
    from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
    removed = await _gas().remove_team_member(db, ctx["operator_id"], member_id)
    if not removed:
        raise HTTPException(404, "Team member not found")
    return {"ok": True}


@router.patch("/api/team/{member_id}/role")
async def update_member_role(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Update a team member's role (owner only)."""
    ctx = await _get_operator_context(request, db)
    if ctx["role"] != "owner":
        raise HTTPException(403, "Only owners can change roles")
    try:
        body = await request.json()
        new_role = body.get("role", "")
    except Exception:
        raise HTTPException(400, "Invalid body")
    from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
    try:
        updated = await _gas().update_member_role(db, ctx["operator_id"], member_id, new_role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Team member not found")
    return {"ok": True}


@router.get("/api/portfolios")
async def list_portfolios(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = await _get_operator_context(request, db)
    items = await _scope_service.list_portfolios(db, ctx["tenant_id"])
    return {"portfolios": items, "count": len(items)}


@router.post("/api/portfolios")
async def create_portfolio(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = await _get_operator_context(request, db)
    if ctx["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Only owners and managers can manage portfolios")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")
    portfolio_key = (body.get("portfolio_key") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()
    if not portfolio_key or not display_name:
        raise HTTPException(400, "portfolio_key and display_name are required")
    portfolio_id = await _scope_service.create_portfolio(
        db,
        ctx["tenant_id"],
        ctx["operator_id"],
        portfolio_key=portfolio_key,
        display_name=display_name,
        description=(body.get("description") or "").strip(),
    )
    if not portfolio_id:
        raise HTTPException(500, "Failed to create portfolio")
    return {"ok": True, "portfolio_id": portfolio_id}


@router.put("/api/portfolios/{portfolio_id}/properties")
async def replace_portfolio_properties(
    portfolio_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = await _get_operator_context(request, db)
    if ctx["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Only owners and managers can manage portfolio properties")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")
    property_external_ids = body.get("property_external_ids") or []
    ok = await _scope_service.replace_portfolio_properties(
        db,
        ctx["tenant_id"],
        portfolio_id,
        [str(value).strip() for value in property_external_ids if str(value).strip()],
    )
    if not ok:
        raise HTTPException(500, "Failed to update portfolio properties")
    return {"ok": True, "portfolio_id": portfolio_id, "property_count": len(property_external_ids)}


@router.get("/api/team/{member_id}/scopes")
async def list_team_member_scopes(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = await _get_operator_context(request, db)
    if ctx["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Only owners and managers can view team scopes")
    scopes = await _scope_service.list_member_scopes(db, ctx["tenant_id"], member_id)
    return {"scopes": scopes, "count": len(scopes)}


@router.put("/api/team/{member_id}/scopes")
async def replace_team_member_scopes(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = await _get_operator_context(request, db)
    if ctx["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Only owners and managers can update team scopes")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")
    scopes = body.get("scopes") or []
    ok = await _scope_service.replace_member_scopes(
        db,
        ctx["tenant_id"],
        member_id,
        scopes,
    )
    if not ok:
        raise HTTPException(500, "Failed to update team scopes")
    return {"ok": True, "member_id": member_id, "count": len(scopes)}


def _send_invite_email_bg(to_email: str, to_name: str, invite_url: str, from_name: str) -> None:
    """Fire-and-forget invite email via SendGrid."""
    import threading
    def _send():
        try:
            import httpx, os as _os
            sgkey = _os.getenv("SENDGRID_API_KEY", "")
            if not sgkey:
                return
            import httpx as _hx
            _hx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sgkey}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": to_email, "name": to_name}],
                                          "subject": f"You've been invited to Oyvoda"}],
                    "from": {"email": "no-reply@oyvoda.com", "name": "Oyvoda"},
                    "content": [{"type": "text/plain",
                                 "value": f"Hi {to_name},\n\n{from_name} has invited you to join their Oyvoda team.\n\nClick here to accept:\n{invite_url}\n\nThis link expires in 7 days.\n\n\u2014 The Oyvoda Team"}],
                },
                timeout=10.0,
            )
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning("Invite email failed: %s", _e)
    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Operational Insights API
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/insights")
async def get_insights(request: Request):
    """
    Returns actionable operational insights derived from:
      - knowledge_gaps × concierge_guest_sessions × market_events (event-correlated gaps)
      - signals table (upcoming demand pressure)
    Never returns raw event lists — only operator-actionable recommendations.
    """
    user = _get_current_user(request)
    if not user:
        from fastapi.responses import JSONResponse as _JR
        return _JR({"error": "Unauthorized"}, status_code=401)

    operator_id = user.get("sub", "")
    tenant_id = user.get("tid", operator_id)

    try:
        from app.core.database import get_db_session
        from sqlalchemy import text
        from fastapi.responses import JSONResponse as _JR
        import json, uuid as _uuid
        from datetime import date, timedelta

        # Resolve market_id for this tenant from market_registry
        market_id = "30a_fl"  # default; replaced by DB lookup below
        try:
            async with get_db_session() as db:
                row = (await db.execute(text("""
                    SELECT market_id FROM market_registry
                    WHERE operator_ids @> CAST(:tid AS jsonb)
                    LIMIT 1
                """), {"tid": json.dumps(tenant_id)})).fetchone()
                if row:
                    market_id = row[0]
        except Exception:
            pass

        from app.services.intelligence.insight_engine import get_insight_engine
        engine = get_insight_engine()
        insights = await engine.run_for_tenant(tenant_id, market_id)

        return _JR({
            "insights": [
                {
                    "insight_id":    ins.insight_id,
                    "insight_type":  ins.insight_type,
                    "title":         ins.title,
                    "body":          ins.body,
                    "action_label":  ins.action_label,
                    "action_target": ins.action_target,
                    "priority":      ins.priority,
                    "session_count": ins.session_count,
                }
                for ins in insights
            ]
        })
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(f"[Insights] API failed: {e}")
        from fastapi.responses import JSONResponse as _JR
        return _JR({"insights": []})  # fail open — never crash the dashboard


# ─────────────────────────────────────────────────────────────────────────────
# Page routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_login(request: Request):
    """Login page — redirect to dashboard if already authenticated."""
    user = _get_current_user(request)
    if user:
        return RedirectResponse("/app/dashboard", status_code=302)
    return HTMLResponse(content=LOGIN_HTML)


@router.get("/dev-login", include_in_schema=False)
async def dev_login(request: Request):
    """Development-only shortcut into the local operator app."""
    if os.getenv("ENVIRONMENT", "development").lower() != "development":
        raise HTTPException(404, "Not found")

    next_path = request.query_params.get("next") or "/app/v2/prebooking"
    email = "operator@oyvoda.com"
    access = _make_access_token("op_001", email, "owner")
    refresh = _make_refresh_token("op_001", email, "owner")
    secure_cookies = _should_use_secure_cookies(request)

    response = HTMLResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="Cache-Control" content="no-store" />
    <title>Signing in…</title>
  </head>
  <body>
    <script>
      try {{
        window.sessionStorage.clear();
        window.localStorage.removeItem("oyvoda_op");
      }} catch (_err) {{}}
      window.location.replace({next_path!r});
    </script>
  </body>
</html>"""
    )
    response.set_cookie(
        "oyvoda_access",
        access,
        httponly=True,
        secure=secure_cookies,
        samesite="lax",
        max_age=_ACCESS_TTL,
        path="/",
    )
    response.set_cookie(
        "oyvoda_refresh",
        refresh,
        httponly=True,
        secure=secure_cookies,
        samesite="lax",
        max_age=_REFRESH_TTL,
        path="/app/auth",
    )
    response.delete_cookie("oyvoda_scoped_op", path="/")
    response.delete_cookie("oyvoda_scoped_tid", path="/")
    return response


@router.get("/dev-login-beach-habitats", include_in_schema=False)
async def dev_login_beach_habitats(request: Request):
    """Development-only shortcut into the real Beach Habitats operator tenant."""
    if os.getenv("ENVIRONMENT", "development").lower() != "development":
        raise HTTPException(404, "Not found")

    next_path = request.query_params.get("next") or "/app/v2/prebooking"
    operator_id = "4d0721d7-3d36-409a-a648-7209ad347a73"
    tenant_id = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"
    email = "lanier@beachhabitats30a.com"

    access = _make_access_token(operator_id, email, "owner", tenant_id=tenant_id)
    refresh = _make_refresh_token(operator_id, email, "owner", tenant_id=tenant_id)
    secure_cookies = _should_use_secure_cookies(request)

    response = HTMLResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="Cache-Control" content="no-store" />
    <title>Signing in…</title>
  </head>
  <body>
    <script>
      try {{
        window.sessionStorage.clear();
        window.localStorage.removeItem("oyvoda_op");
      }} catch (_err) {{}}
      window.location.replace({next_path!r});
    </script>
  </body>
</html>"""
    )
    response.set_cookie(
        "oyvoda_access",
        access,
        httponly=True,
        secure=secure_cookies,
        samesite="lax",
        max_age=_ACCESS_TTL,
        path="/",
    )
    response.set_cookie(
        "oyvoda_refresh",
        refresh,
        httponly=True,
        secure=secure_cookies,
        samesite="lax",
        max_age=_REFRESH_TTL,
        path="/app/auth",
    )
    response.delete_cookie("oyvoda_scoped_op", path="/")
    response.delete_cookie("oyvoda_scoped_tid", path="/")
    return response




@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard(request: Request):
    """Main app shell — requires valid JWT cookie."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/app", status_code=302)
    response = HTMLResponse(content=APP_HTML)
    # Force the authenticated dashboard shell itself to revalidate too.
    # Otherwise browsers can retain an older HTML document that still points
    # at stale asset-version tags even after the JS/CSS files are no-cache.
    response.headers["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/v2", response_class=HTMLResponse, include_in_schema=False)
@router.get("/v2/{path:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard_v2(request: Request, path: str = ""):
    """React dashboard v2 shell — requires valid JWT cookie."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/app", status_code=302)
    response = HTMLResponse(content=_render_v2_shell())
    response.headers["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.post("/messaging-email")
async def set_messaging_email(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Persist the operator's guest-messaging inbox address on operator_accounts.
    Called from the Gmail connect page Step 1 before OAuth, because the login
    email and the monitored inbox are typically different addresses (a common
    source of onboarding confusion).

    Body: {"messaging_email": "inbox@example.com"}
    """
    user = _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    operator_id = user.get("scoped_op") or user.get("sub") or ""
    if not operator_id:
        raise HTTPException(401, "Not authenticated")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    raw = (body.get("messaging_email") or "").strip().lower()
    # Minimal RFC-ish email validation — defensive; we don't trust client
    # validation. Keeps out obvious garbage; Gmail OAuth further validates
    # by requiring the operator to actually own the account.
    import re as _re
    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", raw):
        raise HTTPException(400, "Please enter a valid email address")
    if len(raw) > 320:  # RFC 5321 upper bound
        raise HTTPException(400, "Email address is too long")

    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            UPDATE operator_accounts
            SET messaging_email = :em, updated_at = NOW()
            WHERE id = :oid
        """),
        {"em": raw, "oid": operator_id},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Operator account not found")
    await db.commit()

    logger.info("[Messaging] Operator %s set messaging_email = %s", operator_id, raw)
    return {"ok": True, "messaging_email": raw}


@router.post("/api/gmail/poll-now")
async def poll_gmail_now(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Trigger one immediate Gmail poll for the current operator context.
    Safe support fallback for newly connected inboxes.
    """
    ctx = None
    row = None
    try:
        ctx = await _get_operator_context(request, db)

        from sqlalchemy import text as _text
        row = (await db.execute(
            _text("""
                SELECT gc.refresh_token, gc.watched_email, gc.tenant_id, COALESCE(gc.email_provider, 'gmail') AS email_provider
                FROM operator_gmail_creds gc
                WHERE gc.operator_id = CAST(:oid AS uuid)
                LIMIT 1
            """),
            {"oid": ctx["operator_id"]},
        )).fetchone()
        if not row:
            raise HTTPException(404, "No Gmail inbox connected for this operator")

        from app.services.messaging.inbox_adapters import InboxAdapterBuildError, InboxAdapterConfig, build_inbox_adapter
        from app.services.property_canonical_write_service import get_canonical_property_write_service
        import uuid as _uuid

        if (row.email_provider or "gmail").lower() in {"gmail", "google", "microsoft", "outlook", "office365", "m365"}:
            await get_canonical_property_write_service(db).sync_tenant_sources(_uuid.UUID(str(row.tenant_id)))
        try:
            poller = build_inbox_adapter(
                InboxAdapterConfig(
                    operator_id=ctx["operator_id"],
                    company_id=_uuid.UUID(str(row.tenant_id)),
                    watched_email=row.watched_email,
                    refresh_token=row.refresh_token,
                    provider=row.email_provider or "gmail",
                ),
                db=db,
            )
        except InboxAdapterBuildError as exc:
            raise HTTPException(503, str(exc))
        if not poller:
            raise HTTPException(503, "Inbox adapter is not configured on this server")
        result = await poller.poll()
        fallback_used = False
        if result.messages_found == 0 and not result.errors:
            fallback_used = True
            result = await poller.poll_with_mode(query_mode="recent_inbox")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "[GmailPollNow] Poll failed for operator=%s tenant=%s watched_email=%s provider=%s",
            (ctx or {}).get("operator_id", ""),
            str(getattr(row, "tenant_id", "") or ""),
            str(getattr(row, "watched_email", "") or ""),
            str(getattr(row, "email_provider", "") or "gmail"),
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc) or "Could not poll inbox right now.",
                "operator_id": (ctx or {}).get("operator_id", ""),
                "tenant_id": str(getattr(row, "tenant_id", "") or ""),
                "watched_email": str(getattr(row, "watched_email", "") or ""),
                "provider": str(getattr(row, "email_provider", "") or "gmail"),
            },
            status_code=500,
        )
    debug_rows = []
    pending_count = None
    inquiry_status_counts = None
    try:
        # Polling may leave the session in a failed transaction state if one of
        # the downstream DB writes errors. Debug visibility should never take
        # down the operator workflow, so clear the transaction and read best-effort.
        await db.rollback()
        debug_rows = (await db.execute(
            _text("""
                SELECT draft_id, status, property_external_id, received_at
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                ORDER BY received_at DESC
                LIMIT 5
            """),
            {"tid": str(row.tenant_id)},
        )).mappings().all()
        pending_count = (await db.execute(
            _text("""
                SELECT COUNT(*)
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND status = 'pending_review'
            """),
            {"tid": str(row.tenant_id)},
        )).scalar()
        inquiry_status_row = (await db.execute(
            _text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending_review,
                    COUNT(*) FILTER (WHERE status = 'replied') AS replied,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE received_at >= NOW() - INTERVAL '7 days') AS recent_total,
                    COUNT(*) AS total
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
            """),
            {"tid": str(row.tenant_id)},
        )).mappings().first()
        if inquiry_status_row:
            inquiry_status_counts = {
                "pending_review": int(inquiry_status_row["pending_review"] or 0),
                "replied": int(inquiry_status_row["replied"] or 0),
                "rejected": int(inquiry_status_row["rejected"] or 0),
                "recent_total": int(inquiry_status_row["recent_total"] or 0),
                "total": int(inquiry_status_row["total"] or 0),
            }
    except Exception as debug_exc:
        logger.warning("[GmailPollNow] debug inquiry inspection failed: %s", debug_exc)
    return {
        "ok": True,
        "operator_id": ctx["operator_id"],
        "tenant_id": str(row.tenant_id),
        "watched_email": row.watched_email,
        "query_mode": result.query_mode,
        "fallback_used": fallback_used,
        "messages_found": result.messages_found,
        "messages_processed": result.messages_processed,
        "messages_skipped": result.messages_skipped,
        "pre_booking_routed": result.pre_booking_routed,
        "in_stay_routed": result.in_stay_routed,
        "already_processed_skips": result.already_processed_skips,
        "non_guest_skips": result.non_guest_skips,
        "missing_message_skips": result.missing_message_skips,
        "duplicate_inquiry_skips": result.duplicate_inquiry_skips,
        "new_pending_inquiries": result.new_pending_inquiries,
        "fallback_inquiries_saved": result.fallback_inquiries_saved,
        "errors": result.errors,
        "pending_review_count": int(pending_count) if pending_count is not None else None,
        "inquiry_status_counts": inquiry_status_counts,
        "recent_inquiries": [
            {
                "draft_id": r["draft_id"],
                "status": r["status"],
                "property_external_id": r["property_external_id"] or "",
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
            }
            for r in debug_rows
        ],
        "polled_at": result.polled_at.isoformat(),
    }


@router.get("/connect-gmail", response_class=HTMLResponse, include_in_schema=False)
async def connect_gmail_page(request: Request):
    """Standalone Gmail connect page — popup OAuth flow, works from any logged-in session."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/app", status_code=302)
    if user.get("role") == "super_admin" and not user.get("scoped_op"):
        return RedirectResponse("/app/admin/operators", status_code=302)
    operator_id = user.get("scoped_op") or user.get("sub", "")
    from app.api.v1.endpoints.operator_signup import _build_gmail_auth_url, GMAIL_CID
    gmail_configured = bool(GMAIL_CID)

    # Look up the watched email for this operator so the page can show it clearly
    watched_email_display = "your guest messaging inbox"
    messaging_email_set = False
    try:
        from app.db.session import get_async_session as _gas
        from sqlalchemy import text as _text
        async for db in _gas():
            row = (await db.execute(
                _text("SELECT messaging_email, email FROM operator_accounts WHERE id = CAST(:id AS uuid)"),
                {"id": operator_id}
            )).fetchone()
            if row:
                # Only treat messaging_email as "set" if it's actually been
                # configured — falling back to the login email is a last resort
                # for display and NOT a signal that the operator has decided
                # which inbox to monitor.
                if row.messaging_email:
                    watched_email_display = row.messaging_email
                    messaging_email_set = True
                elif row.email:
                    watched_email_display = row.email
            break
    except Exception:
        pass

    connect_html = f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='UTF-8'>
<meta name='viewport' content='width=device-width,initial-scale=1.0'>
<title>Connect Gmail — Oyvoda</title>
<link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;500;600&display=swap' rel='stylesheet'>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;
  display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.2);border-radius:20px;
  padding:48px;width:100%;max-width:480px;text-align:center;box-shadow:0 32px 80px rgba(0,0,0,0.5)}}
.logo{{font-family:'Cormorant Garamond',serif;font-size:24px;color:#f0ebe3;display:block;
  margin-bottom:32px;text-decoration:none}}
h2{{font-size:20px;font-weight:600;margin-bottom:8px}}
.desc{{font-size:13px;color:rgba(240,235,227,0.45);margin-bottom:20px;line-height:1.7}}
.inbox-box{{background:rgba(200,120,50,0.07);border:1px solid rgba(200,120,50,0.2);border-radius:12px;
  padding:14px 18px;margin-bottom:20px;text-align:left}}
.inbox-label{{font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
  color:rgba(200,120,50,0.7);font-weight:500;margin-bottom:4px}}
.inbox-email{{font-size:15px;color:#f0ebe3;font-weight:500;word-break:break-all}}
.inbox-note{{font-size:11px;color:rgba(240,235,227,0.4);margin-top:4px;line-height:1.5}}
.steps{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:12px;
  padding:18px 20px;margin-bottom:24px;text-align:left}}
.steps-title{{font-size:11px;letter-spacing:0.1em;text-transform:uppercase;
  color:rgba(240,235,227,0.4);margin-bottom:12px;font-weight:500}}
.step-item{{display:flex;align-items:flex-start;gap:12px;margin-bottom:10px;font-size:13px;
  color:rgba(240,235,227,0.65);line-height:1.5}}
.step-item:last-child{{margin-bottom:0}}
.step-num{{background:rgba(200,120,50,0.15);color:#c87832;border-radius:50%;width:20px;height:20px;
  display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;
  flex-shrink:0;margin-top:1px}}
.btn{{display:block;width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;
  padding:14px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none;
  transition:background 0.15s;margin-bottom:12px;font-family:'DM Sans',sans-serif}}
.btn:hover{{background:#e09040}}
.btn:disabled{{opacity:0.5;cursor:not-allowed}}
.btn-sec{{display:block;width:100%;background:transparent;color:rgba(240,235,227,0.35);
  border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px;font-size:13px;
  text-decoration:none;transition:all 0.15s}}
.btn-sec:hover{{color:#f0ebe3;border-color:rgba(255,255,255,0.18)}}
.btn-ter{{display:block;width:100%;background:rgba(255,255,255,0.04);color:#f0ebe3;border:1px solid rgba(255,255,255,0.12);border-radius:10px;padding:12px;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;transition:all 0.15s;margin-bottom:12px;font-family:'DM Sans',sans-serif}}
.btn-ter:hover{{background:rgba(255,255,255,0.07);border-color:rgba(255,255,255,0.18)}}
.btn-ter:disabled{{opacity:0.5;cursor:not-allowed}}
.status{{margin-bottom:16px;padding:12px 16px;border-radius:10px;font-size:13px;display:none}}
.status.info{{background:rgba(200,120,50,0.08);border:1px solid rgba(200,120,50,0.2);
  color:rgba(240,235,227,0.75);display:block}}
.status.success{{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);
  color:#86efac;display:block}}
.status.error{{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);
  color:#fca5a5;display:block}}
.not-configured{{background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15);
  border-radius:12px;padding:16px 18px;margin-bottom:20px;font-size:13px;
  color:rgba(240,235,227,0.55);line-height:1.6}}
</style></head><body>
<div class='card'>
  <a href='/app/dashboard' class='logo'>oyvoda</a>
  <h2>Connect Gmail Inbox</h2>
  <p class='desc'>Allow Oyvoda to monitor your guest messaging inbox.</p>

  <!-- STEP 0: Tell us which inbox to monitor (hidden once messaging_email is saved) -->
  <div id='step0-wrap' style='display:{'none' if messaging_email_set else 'block'}'>
    <div style='background:rgba(200,120,50,0.06);border:1px solid rgba(200,120,50,0.22);border-radius:12px;padding:14px 18px;margin-bottom:16px;text-align:left'>
      <div style='font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#c87832;font-weight:500;margin-bottom:8px'>Step 1 of 2 — Tell us which inbox to monitor</div>
      <div style='font-size:13px;color:rgba(240,235,227,0.75);line-height:1.6;margin-bottom:12px'>
        Your Oyvoda login is separate from the inbox that receives guest inquiries. Enter the email address where Escapia / Vrbo / Airbnb messages are forwarded.
      </div>
      <div style='display:flex;gap:8px;margin-top:10px'>
        <input id='messaging-email-input' type='email' placeholder='inbox@example.com'
          style='flex:1;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:10px 14px;font-size:13px;color:#f0ebe3;font-family:"DM Sans",sans-serif;outline:none' />
        <button id='save-email-btn' onclick='saveMessagingEmail()'
          style='background:#c87832;color:#fff;border:none;border-radius:8px;padding:10px 16px;font-size:13px;font-weight:600;cursor:pointer;font-family:"DM Sans",sans-serif'>Save →</button>
      </div>
      <div id='email-err' style='font-size:12px;color:#fca5a5;margin-top:8px;display:none'></div>
    </div>
    <a href='/app/dashboard' class='btn-sec'>Return to dashboard</a>
  </div>

  <!-- STEP 1: OAuth connect (visible once messaging_email is saved) -->
  <div id='step1-wrap' style='display:{'block' if messaging_email_set else 'none'}'>
    <div class='inbox-box'>
      <div class='inbox-label'>Inbox Oyvoda will monitor</div>
      <div class='inbox-email' id='inbox-email-display'>{watched_email_display}</div>
      <div class='inbox-note'>This is where your Vrbo / Escapia guest messages are forwarded.
      Sign in with the Google account that owns this address. <a href='javascript:void(0)' onclick='changeEmail()' style='color:#c87832'>Change</a></div>
    </div>

    <!-- Escapia pre-step callout — most operators forget to configure forwarding before OAuth, which means we connect to a Gmail inbox that never receives anything. -->
    <div style='background:rgba(200,120,50,0.06);border:1px solid rgba(200,120,50,0.22);border-radius:12px;padding:14px 18px;margin-bottom:20px;text-align:left'>
      <div style='font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#c87832;font-weight:500;margin-bottom:8px'>⚠ Before you connect</div>
      <div style='font-size:13px;color:rgba(240,235,227,0.75);line-height:1.6;margin-bottom:6px'>
        Escapia sends guest inquiries to the email address on your Escapia account. For Oyvoda to see them, forward those emails to <strong style='color:#f0ebe3' id='fwd-email-display'>{watched_email_display}</strong>.
      </div>
      <div style='font-size:12px;color:rgba(240,235,227,0.5);line-height:1.6'>
        In Escapia: <em>Company Settings → Email Notifications → add the forwarded recipient for "Inquiry" and "Reservation" events.</em> If you’re not sure how, ping us at support@oyvoda.com and we’ll walk you through it.
      </div>
    </div>

    <div class='steps'>
      <div class='steps-title'>What happens next</div>
      <div class='step-item'><div class='step-num'>1</div><div>A Google sign-in window opens — sign in with the account that owns <strong style='color:#f0ebe3' id='step1-email-display'>{watched_email_display}</strong></div></div>
      <div class='step-item'><div class='step-num'>2</div><div>Click <strong style='color:#f0ebe3'>Allow</strong> when Google asks for inbox access</div></div>
      <div class='step-item'><div class='step-num'>3</div><div>Oyvoda polls your inbox every 5 minutes and parses guest inquiries automatically</div></div>
      <div class='step-item'><div class='step-num'>4</div><div>Inquiries show up in <strong style='color:#f0ebe3'>Messages</strong> with AI-drafted replies waiting for your review</div></div>
    </div>

    <div id='status' class='status'></div>

    {'<div class="not-configured">⚠ Gmail OAuth is not configured on this server.</div>' if not gmail_configured else ''}

    <button class='btn' id='connect-btn' onclick='startConnect()'
      {'disabled' if not gmail_configured else ''}>
      Connect with Google →
    </button>
    <button class='btn-ter' id='poll-btn' onclick='pollInboxNow()'>
      Poll Inbox Now
    </button>
    <div id='poll-breakdown' style='display:none;text-align:left;margin-top:14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 16px'>
      <div style='font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#c87832;font-weight:600;margin-bottom:8px'>Last poll breakdown</div>
      <div id='poll-breakdown-body' style='font-size:12px;color:rgba(240,235,227,0.72);line-height:1.7'></div>
    </div>
    <a href='/app/dashboard' class='btn-sec' id='cancel-link'>Return to dashboard</a>
  </div>
</div>
<script>
var OPERATOR_ID = '{operator_id}';
var connected = false;

// Handle tab-redirect fallback: callback redirected back here with ?connected=google
(function() {{
  var params = new URLSearchParams(window.location.search);
  var connectedParam = params.get('connected');
  if (connectedParam === 'google') {{
    connected = true;
    setStatus('success', '\u2713 Gmail connected successfully! Redirecting to dashboard...');
    document.getElementById('cancel-link').textContent = 'Return to dashboard';
    var btn = document.getElementById('connect-btn');
    btn.textContent = '\u2713 Connected';
    btn.style.background = 'rgba(34,197,94,0.2)';
    btn.style.color = '#86efac';
    btn.style.border = '1px solid rgba(34,197,94,0.3)';
    btn.disabled = true;
    // Clean URL without reloading
    window.history.replaceState({{}}, '', '/app/connect-gmail');
    setTimeout(() => {{ window.location.href = '/app/dashboard'; }}, 2000);
  }}
}})();

function setStatus(kind, msg) {{
  var el = document.getElementById('status');
  el.className = 'status ' + kind;
  el.textContent = msg;
}}

function setPollBreakdown(lines) {{
  var wrap = document.getElementById('poll-breakdown');
  var body = document.getElementById('poll-breakdown-body');
  if (!wrap || !body) return;
  if (!lines || !lines.length) {{
    wrap.style.display = 'none';
    body.innerHTML = '';
    return;
  }}
  body.innerHTML = lines.map(function(line) {{
    return '<div>• ' + line + '</div>';
  }}).join('');
  wrap.style.display = 'block';
}}

function startConnect() {{
  if (!OPERATOR_ID) {{ setStatus('error', 'Session expired. Please sign in again.'); return; }}
  setStatus('info', 'Opening Google sign-in window...');
  var btn = document.getElementById('connect-btn');
  btn.disabled = true;
  btn.textContent = 'Opening sign-in...';

  fetch('/app/gmail-auth-url?operator_id=' + OPERATOR_ID)
    .then(r => r.json())
    .then(data => {{
      if (!data.url) {{
        setStatus('error', 'Google sign-in is not available right now. Please try again later.');
        btn.disabled = false; btn.textContent = 'Connect with Google →';
        return;
      }}
      var popup = window.open(data.url, 'gmail_auth',
        'width=560,height=660,left='+Math.round((screen.width-560)/2)+',top='+Math.round((screen.height-660)/2));
      if (!popup || popup.closed) {{
        // Popup blocked — fall back to redirect
        setStatus('info', 'Popup was blocked. Continuing in this tab...');
        setTimeout(() => {{ window.location.href = data.url; }}, 1200);
        return;
      }}
      setStatus('info', 'Google sign-in is open. Complete the steps in that window...');
      var poll = setInterval(() => {{
        if (popup.closed) {{
          clearInterval(poll);
          // Check if callback set the success flag
          if (sessionStorage.getItem('inbox_connected') === 'google') {{
            sessionStorage.removeItem('inbox_connected');
            connected = true;
            setStatus('success', '\u2713 Gmail connected successfully! Redirecting to dashboard...');
            document.getElementById('cancel-link').textContent = 'Return to dashboard';
            btn.textContent = '\u2713 Connected';
            btn.style.background = 'rgba(34,197,94,0.2)';
            btn.style.color = '#86efac';
            btn.style.border = '1px solid rgba(34,197,94,0.3)';
            setTimeout(() => {{ window.location.href = '/app/dashboard'; }}, 1800);
          }} else {{
            // Window closed without completing — reset
            setStatus('info', 'Sign-in was not completed. You can try again or come back later.');
            btn.disabled = false;
            btn.textContent = 'Try Again →';
          }}
        }}
      }}, 500);
    }})
    .catch(() => {{
      setStatus('error', 'Something went wrong. Please refresh and try again.');
      btn.disabled = false; btn.textContent = 'Connect with Google →';
    }});
}}

function pollInboxNow() {{
  function errText(v) {{
    if (!v) return '';
    if (typeof v === 'string') return v;
    if (typeof v.detail === 'string') return v.detail;
    if (typeof v.error === 'string') return v.error;
    try {{ return JSON.stringify(v); }} catch (_) {{ return String(v); }}
  }}
  var btn = document.getElementById('poll-btn');
  var original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Polling inbox...';
  setPollBreakdown([]);
  setStatus('info', 'Checking ' + document.getElementById('inbox-email-display').textContent + ' for unread guest messages first, then recent inbox mail if needed...');

  fetch('/app/api/gmail/poll-now', {{
    method: 'POST',
    credentials: 'include',
    headers: {{ 'Content-Type': 'application/json' }}
  }})
    .then(async (r) => {{
      const data = await r.json().catch(() => ({{}}));
      if (!r.ok || !data.ok) throw new Error(errText(data) || 'Could not poll inbox');
      var modeLabel = data.query_mode === 'recent_inbox' ? 'recent inbox messages' : 'unread messages';
      var summary = 'Found ' + (data.messages_found || 0) + ' ' + modeLabel;
      summary += ', processed ' + (data.messages_processed || 0);
      summary += ', routed ' + ((data.pre_booking_routed || 0) + (data.in_stay_routed || 0));
      if (data.fallback_used && data.query_mode === 'recent_inbox') {{
        summary += ' using fallback search';
      }}
      if (typeof data.pending_review_count === 'number') {{
        summary += '. Pending review queue: ' + data.pending_review_count;
      }}
      if (data.inquiry_status_counts) {{
        summary += ' Status counts'
          + ' p=' + (data.inquiry_status_counts.pending_review || 0)
          + ', r=' + (data.inquiry_status_counts.replied || 0)
          + ', x=' + (data.inquiry_status_counts.rejected || 0)
          + ', recent=' + (data.inquiry_status_counts.recent_total || 0);
      }}
      var guidance = [];
      if (data.new_pending_inquiries) guidance.push((data.new_pending_inquiries || 0) + ' new queue item(s)');
      if (data.duplicate_inquiry_skips) guidance.push((data.duplicate_inquiry_skips || 0) + ' duplicate inquiry thread(s)');
      if (data.already_processed_skips) guidance.push((data.already_processed_skips || 0) + ' already processed');
      if (data.non_guest_skips) guidance.push((data.non_guest_skips || 0) + ' non-guest email(s)');
      if (data.missing_message_skips) guidance.push((data.missing_message_skips || 0) + ' missing/deleted email(s)');
      if (data.fallback_inquiries_saved) guidance.push((data.fallback_inquiries_saved || 0) + ' fallback draft(s) saved');
      if (guidance.length) {{
        summary += '. Why not all 25: ' + guidance.join(', ');
      }}
      var breakdown = [];
      breakdown.push('Search mode: ' + (data.query_mode === 'recent_inbox' ? 'recent inbox fallback' : 'unread inbox'));
      breakdown.push('New review queue items: ' + (data.new_pending_inquiries || 0));
      breakdown.push('Duplicate inquiry threads skipped: ' + (data.duplicate_inquiry_skips || 0));
      breakdown.push('Already processed skips: ' + (data.already_processed_skips || 0));
      breakdown.push('Non-guest skips: ' + (data.non_guest_skips || 0));
      breakdown.push('Missing or deleted emails: ' + (data.missing_message_skips || 0));
      if (data.fallback_inquiries_saved) breakdown.push('Fallback drafts saved for manual review: ' + (data.fallback_inquiries_saved || 0));
      if (typeof data.pending_review_count === 'number') breakdown.push('Current pending review queue: ' + data.pending_review_count);
      setPollBreakdown(breakdown);
      if (data.errors && data.errors.length) {{
        setStatus('error', summary + '. Errors: ' + data.errors.join(' | '));
      }} else {{
        setStatus('success', summary + '.');
      }}
    }})
    .catch((e) => {{
      setPollBreakdown([]);
      setStatus('error', errText(e && e.message ? e.message : e) || 'Could not poll inbox right now.');
    }})
    .finally(() => {{
      btn.disabled = false;
      btn.textContent = original;
    }});
}}

// Save the messaging inbox address, then reveal Step 2 (OAuth)
function saveMessagingEmail() {{
  var input = document.getElementById('messaging-email-input');
  var err = document.getElementById('email-err');
  var btn = document.getElementById('save-email-btn');
  var val = (input.value || '').trim();
  err.style.display = 'none';
  // Minimal email shape check — server validates more strictly
  if (!val || val.indexOf('@') < 1 || val.indexOf('.') < 0) {{
    err.textContent = 'Please enter a valid email address.';
    err.style.display = 'block';
    return;
  }}
  btn.disabled = true;
  btn.textContent = 'Saving...';
  fetch('/app/messaging-email', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    credentials: 'include',
    body: JSON.stringify({{messaging_email: val}}),
  }}).then(r => r.json().then(d => ({{ok: r.ok, d: d}}))).then(res => {{
    if (!res.ok || !res.d.ok) throw new Error((res.d && res.d.detail) || 'Save failed');
    document.getElementById('inbox-email-display').textContent = val;
    document.getElementById('fwd-email-display').textContent = val;
    document.getElementById('step1-email-display').textContent = val;
    document.getElementById('step0-wrap').style.display = 'none';
    document.getElementById('step1-wrap').style.display = 'block';
  }}).catch(e => {{
    err.textContent = (e && e.message) || 'Could not save. Please try again.';
    err.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Save →';
  }});
}}

// Let operator revise the inbox address before OAuth
function changeEmail() {{
  var input = document.getElementById('messaging-email-input');
  if (input) {{
    input.value = document.getElementById('inbox-email-display').textContent || '';
  }}
  document.getElementById('step0-wrap').style.display = 'block';
  document.getElementById('step1-wrap').style.display = 'none';
  if (input) input.focus();
}}
</script>
</body></html>"""
    return HTMLResponse(content=connect_html)
