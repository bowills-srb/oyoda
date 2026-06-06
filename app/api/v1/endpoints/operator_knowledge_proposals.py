"""
operator_knowledge_proposals.py — Operator-facing review queue for the
brain learning loop's durable-edit proposals.

When an operator edits an AI draft in the pre-booking queue and the edit is
"durable" (a fact/policy/price change, not a style tweak), the brain-side
DraftLearningService (app/services/messaging_brain/learning) records the edit
in operator_draft_events AND proposes an ExtractionCandidate via the shared
ExtractionStagingService. Those candidates land in extraction_candidates with
proposed_metadata.source == "operator_draft_edit".

This router exposes that backlog to the operator so they can review each
proposed knowledge addition, choose its scope (this property / a property
group / company-wide), and approve it into durable scoped knowledge — or
reject it. Approval routes through the SAME staging-service promotion path
used by document ingestion, writing to concierge_scoped_knowledge.

Scope choices map to ExtractionStagingService._ALLOWED_SCOPE_TYPES:
    property        -> scope_target_id = the property's UUID
    property_group  -> scope_target_id = a property_group UUID
    tenant          -> scope_target_id = the company/tenant UUID (company-wide)

Auth: httpOnly JWT cookie, mirroring operator_prebooking.py exactly.
All routes are under /app/api/ to match the dashboard JS conventions.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.db.session import get_async_session
from app.services.extraction.staging_service import (
    ExtractionCandidate,
    get_extraction_staging_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api", tags=["Operator Knowledge Proposals"])

# Candidates created by the brain draft-learning loop carry this marker in
# proposed_metadata.source. We filter to it so the operator's learning-review
# queue shows only draft-edit proposals, not document-ingestion candidates.
_DRAFT_EDIT_SOURCE = "operator_draft_edit"

# Scope choices the operator may pick, mapped to staging-service scope types.
# "none" is handled at the UI layer (simply don't promote) and never reaches
# here; the API only accepts scopes that result in a real promotion.
_ALLOWED_OPERATOR_SCOPES = {"property", "property_group", "tenant"}


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers — mirror operator_prebooking.py to avoid a circular import.
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < time.time():
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
    except Exception:
        return None


def _require_user(request: Request) -> dict:
    user = _get_current_user(request)
    if not user:
        raise ValueError("Not authenticated")
    return user


def _tenant_id_from_user(user: dict) -> str:
    operator_id = user.get("scoped_op") or user.get("sub", "")
    return user.get("tid") or user.get("tenant_id") or operator_id


def _operator_user_id(user: dict) -> str:
    # The reviewing user id recorded on the candidate. Prefer the real
    # operator sub; fall back to scoped_op for super-admins acting into a tenant.
    return user.get("sub") or user.get("scoped_op") or _tenant_id_from_user(user)


def _has_valid_tenant_id(tenant_id: str) -> bool:
    return bool(tenant_id) and len(tenant_id) == 36 and tenant_id.count("-") == 4


def _tenant_scope_response(empty_payload: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": "No tenant context", "detail": "No tenant context", **(empty_payload or {})},
        status_code=403,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────────────────

def _is_draft_edit_candidate(candidate: ExtractionCandidate) -> bool:
    meta = candidate.proposed_metadata or {}
    return str(meta.get("source") or "") == _DRAFT_EDIT_SOURCE


def _serialize_candidate(candidate: ExtractionCandidate) -> dict:
    """Operator-facing shape for one draft-edit proposal.

    Surfaces the before/after so the operator can see exactly what they changed,
    plus the edit classification and the proposed knowledge that would be stored.
    """
    meta = candidate.proposed_metadata or {}
    return {
        "candidate_id": str(candidate.candidate_id),
        "scope_type": candidate.scope_type,
        "scope_target_id": str(candidate.scope_target_id),
        "confidence": candidate.confidence,
        "review_status": candidate.review_status,
        # The proposed knowledge that promotion would write.
        "proposed_question": candidate.proposed_question_text or "",
        "proposed_answer": candidate.proposed_answer_text or "",
        "proposed_topic_id": candidate.proposed_topic_id,
        # Provenance from the draft edit (so the operator sees the diff context).
        "edit_type": meta.get("edit_type") or "",
        "original_draft": meta.get("original_draft") or "",
        "draft_id": meta.get("draft_id") or "",
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /app/api/knowledge-proposals — list pending draft-edit proposals
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/knowledge-proposals")
async def list_knowledge_proposals(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Pending knowledge proposals from operator draft edits, newest first."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response({"count": 0, "items": []})

    staging = get_extraction_staging_service()
    try:
        pending = await staging.get_pending_candidates(db, tenant_id)
    except Exception as exc:
        logger.exception("[KnowledgeProposals] list failed")
        return JSONResponse({"error": str(exc), "count": 0, "items": []}, status_code=500)

    # Filter to brain draft-edit proposals only; document-ingestion candidates
    # are reviewed elsewhere and would otherwise clutter the learning queue.
    items = [
        _serialize_candidate(candidate)
        for candidate in pending
        if _is_draft_edit_candidate(candidate)
    ]
    # Newest first — get_pending_candidates returns created_at ASC.
    items.reverse()
    return JSONResponse({"count": len(items), "items": items})


# ────────────────────────────────────────────────────────────────
# GET /app/api/property-groups — list this tenant's property groups
# ────────────────────────────────────────────────────────────────
# These are the real UUID-keyed groups (property_groups table, migration 076)
# used as the scope_target_id when an operator promotes a proposal to
# property_group scope. Distinct from the key-based "portfolios" concept —
# scoped knowledge keys groups by property_groups.id (a UUID), so the scope
# picker must use these ids, not portfolio keys.

@router.get("/property-groups")
async def list_property_groups(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Active property groups for this tenant: {id, name, group_type}."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response({"count": 0, "items": []})

    try:
        # Guard against environments where the table predates migration 076.
        exists = (
            await db.execute(
                text(
                    "SELECT to_regclass('public.property_groups') IS NOT NULL AS present"
                )
            )
        ).scalar()
        if not exists:
            return JSONResponse({"count": 0, "items": []})

        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, name, group_type
                    FROM property_groups
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND is_active = TRUE
                    ORDER BY name ASC
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()
    except Exception as exc:
        logger.exception("[KnowledgeProposals] property-groups list failed")
        return JSONResponse({"error": str(exc), "count": 0, "items": []}, status_code=500)

    items = [
        {
            "id": str(row["id"]),
            "name": str(row["name"] or ""),
            "group_type": str(row["group_type"] or ""),
        }
        for row in rows
    ]
    return JSONResponse({"count": len(items), "items": items})


# ────────────────────────────────────────────────────────────────
# POST /app/api/property-groups — create a new property group
# ────────────────────────────────────────────────────────────────
# Lets an operator define a new group (e.g. a condo complex or HOA) so that
# group-scoped knowledge and membership tagging have a target. Name is unique
# per tenant (case-insensitive, enforced by ux_property_groups_tenant_name);
# if an active group with the same name already exists we return it rather than
# erroring, so the action is idempotent from the operator's point of view.

_ALLOWED_GROUP_TYPES = {"neighborhood", "condo_complex", "portfolio_segment", "custom"}


@router.post("/property-groups")
async def create_property_group(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Create a property group for this tenant. Body: {name, group_type?, description?}."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = str(body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if len(name) > 120:
        return JSONResponse({"error": "name too long (max 120 chars)"}, status_code=400)

    group_type = str(body.get("group_type") or "neighborhood").strip().lower()
    if group_type not in _ALLOWED_GROUP_TYPES:
        group_type = "neighborhood"
    description = str(body.get("description") or "").strip() or None

    try:
        exists = (
            await db.execute(
                text("SELECT to_regclass('public.property_groups') IS NOT NULL AS present")
            )
        ).scalar()
        if not exists:
            return JSONResponse({"error": "property groups are not available"}, status_code=409)

        # Idempotent on name: if an active group with this name (case-insensitive)
        # already exists for the tenant, return it instead of violating the
        # unique index. Operators re-typing an existing group get the existing one.
        existing = (
            await db.execute(
                text(
                    """
                    SELECT id, name, group_type
                    FROM property_groups
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND is_active = TRUE
                      AND LOWER(name) = LOWER(:name)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id, "name": name},
            )
        ).mappings().first()
        if existing:
            return JSONResponse(
                {
                    "ok": True,
                    "already_existed": True,
                    "id": str(existing["id"]),
                    "name": str(existing["name"] or ""),
                    "group_type": str(existing["group_type"] or ""),
                }
            )

        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO property_groups (tenant_id, name, group_type, description)
                    VALUES (CAST(:tid AS uuid), :name, :gtype, :descr)
                    RETURNING id, name, group_type
                    """
                ),
                {"tid": tenant_id, "name": name, "gtype": group_type, "descr": description},
            )
        ).mappings().first()
        await db.commit()
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[PropertyGroups] create failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "already_existed": False,
            "id": str(row["id"]),
            "name": str(row["name"] or ""),
            "group_type": str(row["group_type"] or ""),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/knowledge-proposals/{candidate_id}/approve
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/knowledge-proposals/{candidate_id}/approve")
async def approve_knowledge_proposal(
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Approve a proposal into durable scoped knowledge at the chosen scope.

    Body:
      scope_type:       "property" | "property_group" | "tenant"
      scope_target_id:  UUID of the property / group; ignored for "tenant"
                        (company-wide uses the tenant id automatically).
      proposed_answer:  optional edited answer text (operator can refine before promote)
      proposed_question: optional edited question text
    """
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    scope_type = str(body.get("scope_type") or "").strip().lower()
    if scope_type not in _ALLOWED_OPERATOR_SCOPES:
        return JSONResponse(
            {"error": f"scope_type must be one of {sorted(_ALLOWED_OPERATOR_SCOPES)}"},
            status_code=400,
        )

    # Resolve the scope target. Company-wide (tenant) always targets the tenant
    # id; property / property_group require an explicit target from the operator.
    if scope_type == "tenant":
        scope_target_id = tenant_id
    else:
        scope_target_id = str(body.get("scope_target_id") or "").strip()
        if not _has_valid_tenant_id(scope_target_id):
            return JSONResponse(
                {"error": f"scope_target_id (a valid UUID) is required for scope_type={scope_type}"},
                status_code=400,
            )

    staging = get_extraction_staging_service()

    # Guard: only act on a draft-edit candidate that belongs to this tenant.
    try:
        pending = await staging.get_pending_candidates(db, tenant_id)
    except Exception as exc:
        logger.exception("[KnowledgeProposals] approve preflight failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    target = next(
        (c for c in pending if str(c.candidate_id) == candidate_id and _is_draft_edit_candidate(c)),
        None,
    )
    if target is None:
        return JSONResponse(
            {"error": "Proposal not found, not pending, or not a draft-edit proposal"},
            status_code=404,
        )

    # Defense-in-depth: verify the chosen promotion target belongs to this
    # tenant before writing scoped knowledge. The candidate is already the
    # tenant's (verified above), but scope_target_id came from the request body.
    if not await _scope_target_belongs_to_tenant(
        db,
        scope_type=scope_type,
        scope_target_id=scope_target_id,
        tenant_id=tenant_id,
    ):
        return JSONResponse(
            {"error": "scope_target_id does not belong to this tenant"},
            status_code=403,
        )

    # edits override the candidate's scope and (optionally) the proposed text,
    # then approve_candidate promotes through the shared scoped-knowledge path.
    edits: dict = {"scope_type": scope_type, "scope_target_id": scope_target_id}
    if isinstance(body.get("proposed_answer"), str) and body["proposed_answer"].strip():
        edits["proposed_answer_text"] = body["proposed_answer"].strip()
    if isinstance(body.get("proposed_question"), str) and body["proposed_question"].strip():
        edits["proposed_question_text"] = body["proposed_question"].strip()
    if isinstance(body.get("review_notes"), str) and body["review_notes"].strip():
        edits["review_notes"] = body["review_notes"].strip()

    try:
        result = await staging.approve_candidate(
            db,
            candidate_id=candidate_id,
            reviewed_by_user_id=_operator_user_id(user),
            edits=edits,
        )
        await db.commit()
    except ValueError as exc:
        await _rollback_quietly(db)
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[KnowledgeProposals] approve failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({
        "ok": True,
        "candidate_id": str(result.candidate_id),
        "review_status": result.review_status,
        "promoted_to_table": result.promoted_to_table,
        "promoted_to_id": str(result.promoted_to_id) if result.promoted_to_id else None,
        "scope_type": scope_type,
        "scope_target_id": scope_target_id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/knowledge-proposals/{candidate_id}/reject
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/knowledge-proposals/{candidate_id}/reject")
async def reject_knowledge_proposal(
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Reject a proposal — the edit was a one-off, not durable knowledge."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response()

    try:
        body = await request.json()
    except Exception:
        body = {}
    notes = str(body.get("review_notes") or "").strip() or None

    staging = get_extraction_staging_service()

    # Guard: only reject a draft-edit candidate belonging to this tenant.
    try:
        pending = await staging.get_pending_candidates(db, tenant_id)
    except Exception as exc:
        logger.exception("[KnowledgeProposals] reject preflight failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    target = next(
        (c for c in pending if str(c.candidate_id) == candidate_id and _is_draft_edit_candidate(c)),
        None,
    )
    if target is None:
        return JSONResponse(
            {"error": "Proposal not found, not pending, or not a draft-edit proposal"},
            status_code=404,
        )

    try:
        result = await staging.reject_candidate(
            db,
            candidate_id=candidate_id,
            reviewed_by_user_id=_operator_user_id(user),
            notes=notes,
        )
        await db.commit()
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[KnowledgeProposals] reject failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({
        "ok": True,
        "candidate_id": str(result.candidate_id),
        "review_status": result.review_status,
    })


async def _rollback_quietly(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


# ───────────────────────────────────────────────────────────────
# Property group membership editing
# ───────────────────────────────────────────────────────────────
# property_group_memberships is the LOAD-BEARING grouping representation: the
# scoped-knowledge retrieval layer reads it (see ScopedKnowledgeService.
# _load_group_ids_for_property) to decide which group-scoped knowledge applies
# to a property. properties.community is a display label only. So correcting a
# mis-tagged property means editing memberships here.
#
# GET  /app/api/properties/{property_id}/groups  -> current membership group ids
# PUT  /app/api/properties/{property_id}/groups  -> replace the full set (idempotent)

async def _property_belongs_to_tenant(db: AsyncSession, property_id: str, tenant_id: str) -> bool:
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT 1 FROM properties
                    WHERE id = CAST(:pid AS uuid) AND tenant_id = CAST(:tid AS uuid)
                    LIMIT 1
                    """
                ),
                {"pid": property_id, "tid": tenant_id},
            )
        ).first()
        return row is not None
    except Exception:
        logger.exception("[PropertyGroups] property ownership check failed")
        return False


@router.get("/properties/{property_id}/groups")
async def get_property_groups(
    property_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Current property-group memberships for this property: list of group ids."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response({"member_group_ids": []})
    if not _has_valid_tenant_id(property_id):
        return JSONResponse({"error": "invalid property_id"}, status_code=400)
    if not await _property_belongs_to_tenant(db, property_id, tenant_id):
        return JSONResponse({"error": "property not found for this tenant"}, status_code=404)

    try:
        exists = (
            await db.execute(
                text("SELECT to_regclass('public.property_group_memberships') IS NOT NULL AS present")
            )
        ).scalar()
        if not exists:
            return JSONResponse({"member_group_ids": []})
        rows = (
            await db.execute(
                text(
                    """
                    SELECT property_group_id
                    FROM property_group_memberships
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND property_id = CAST(:pid AS uuid)
                    """
                ),
                {"tid": tenant_id, "pid": property_id},
            )
        ).mappings().all()
    except Exception as exc:
        logger.exception("[PropertyGroups] membership read failed")
        return JSONResponse({"error": str(exc), "member_group_ids": []}, status_code=500)

    return JSONResponse({"member_group_ids": [str(r["property_group_id"]) for r in rows]})


@router.put("/properties/{property_id}/groups")
async def set_property_groups(
    property_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Replace this property's full set of group memberships (idempotent).

    Body: { "group_ids": ["<uuid>", ...] }  — the complete desired set. Groups
    not in the list are removed; new ones are added. Every group id must belong
    to this tenant (ownership-guarded). Empty list clears all memberships.
    """
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response()
    if not _has_valid_tenant_id(property_id):
        return JSONResponse({"error": "invalid property_id"}, status_code=400)
    if not await _property_belongs_to_tenant(db, property_id, tenant_id):
        return JSONResponse({"error": "property not found for this tenant"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    raw_ids = body.get("group_ids")
    if not isinstance(raw_ids, list):
        return JSONResponse({"error": "group_ids must be a list"}, status_code=400)
    desired = [str(g).strip() for g in raw_ids if str(g).strip()]
    # Dedupe while preserving validity check below.
    desired = list(dict.fromkeys(desired))
    for gid in desired:
        if not _has_valid_tenant_id(gid):
            return JSONResponse({"error": f"invalid group id: {gid}"}, status_code=400)

    try:
        exists = (
            await db.execute(
                text("SELECT to_regclass('public.property_group_memberships') IS NOT NULL AS present")
            )
        ).scalar()
        if not exists:
            return JSONResponse({"error": "property groups are not available"}, status_code=409)

        # Ownership guard: every desired group must belong to this tenant.
        if desired:
            owned_rows = (
                await db.execute(
                    text(
                        """
                        SELECT id FROM property_groups
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND is_active = TRUE
                          AND id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"tid": tenant_id, "ids": desired},
                )
            ).mappings().all()
            owned = {str(r["id"]) for r in owned_rows}
            invalid = [g for g in desired if g not in owned]
            if invalid:
                return JSONResponse(
                    {"error": f"group(s) not found for this tenant: {invalid}"},
                    status_code=403,
                )

        # Reconcile: delete everything for this property, then insert the desired
        # set. Simple, idempotent, and correct for the small N of groups here.
        await db.execute(
            text(
                """
                DELETE FROM property_group_memberships
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND property_id = CAST(:pid AS uuid)
                """
            ),
            {"tid": tenant_id, "pid": property_id},
        )
        for gid in desired:
            await db.execute(
                text(
                    """
                    INSERT INTO property_group_memberships
                        (property_id, property_group_id, tenant_id)
                    VALUES (CAST(:pid AS uuid), CAST(:gid AS uuid), CAST(:tid AS uuid))
                    ON CONFLICT (property_id, property_group_id) DO NOTHING
                    """
                ),
                {"pid": property_id, "gid": gid, "tid": tenant_id},
            )
        await db.commit()
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[PropertyGroups] membership write failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({"ok": True, "member_group_ids": desired})


# ───────────────────────────────────────────────────────────────
# GET /app/api/property-group-reconcile — community vs membership drift report
# ───────────────────────────────────────────────────────────────
# READ-ONLY diagnostic. There are two grouping representations:
#   properties.community          — a text slug (e.g. "grayton_beach"), display+filter
#   property_group_memberships    — UUID links, the LOAD-BEARING thing retrieval reads
# These are linked only by NAME similarity (no structural key). This endpoint
# reports where they disagree so an operator can fix each via the membership
# editor. It NEVER writes — a fuzzy name match must not silently mutate the
# load-bearing table. Classifications per property:
#   ok                    — community matches a membership (or no community set)
#   missing_membership    — community names a group that exists, but no membership
#   mismatched_membership — member of group(s) that don't match the community
#   community_no_group    — community set, but no group with a matching name exists
# Only "ok" items are omitted from the report; the rest are returned for review.

def _normalize_group_token(value: str) -> str:
    """Canonicalize a community slug or a group name to a comparable token.

    Lowercase, collapse whitespace/underscores to single underscores, strip a
    trailing '_beach' so 'blue_mountain' (community) and 'Blue Mountain Beach'
    (group) compare equal. Suffix-tolerant matching is applied by the caller
    via _tokens_match; this just produces the base token.
    """
    token = "_".join(str(value or "").strip().lower().replace("-", " ").split())
    token = token.replace("__", "_")
    return token


def _tokens_match(community_token: str, group_token: str) -> bool:
    """True if a community token and a group-name token refer to the same place.

    Tolerates a trailing '_beach' on either side (the seed's COMMUNITIES map is
    inconsistent: 'grayton_beach' keeps it, 'blue_mountain' drops it), without
    over-collapsing distinct communities.
    """
    if not community_token or not group_token:
        return False
    if community_token == group_token:
        return True
    c = community_token[:-6] if community_token.endswith("_beach") else community_token
    g = group_token[:-6] if group_token.endswith("_beach") else group_token
    return c == g and bool(c)


@router.get("/property-group-reconcile")
async def property_group_reconcile(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Report properties whose community label and group memberships disagree."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response({"count": 0, "items": []})

    try:
        groups_exist = (
            await db.execute(
                text("SELECT to_regclass('public.property_groups') IS NOT NULL AS present")
            )
        ).scalar()
        if not groups_exist:
            # No grouping infrastructure in this environment; nothing to reconcile.
            return JSONResponse({"count": 0, "items": [], "groups": []})

        # All active groups for the tenant (id + name), for name matching + labels.
        group_rows = (
            await db.execute(
                text(
                    """
                    SELECT id, name
                    FROM property_groups
                    WHERE tenant_id = CAST(:tid AS uuid) AND is_active = TRUE
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()

        # All properties for the tenant with their community label.
        # property_code is guaranteed to exist (seed writes it); display_name /
        # property_name are coalesced for a friendlier label but we fall back to
        # property_code so a missing optional column can't break the query.
        prop_rows = (
            await db.execute(
                text(
                    """
                    SELECT id,
                           COALESCE(property_code, '') AS name,
                           COALESCE(community, '') AS community
                    FROM properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()

        # Current memberships for the tenant: property_id -> [group_id, ...].
        mem_rows = (
            await db.execute(
                text(
                    """
                    SELECT property_id, property_group_id
                    FROM property_group_memberships
                    WHERE tenant_id = CAST(:tid AS uuid)
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()
    except Exception as exc:
        logger.exception("[PropertyGroupReconcile] query failed")
        return JSONResponse({"error": str(exc), "count": 0, "items": []}, status_code=500)

    # Index groups by id and by normalized name token.
    group_name_by_id: dict[str, str] = {str(g["id"]): str(g["name"] or "") for g in group_rows}
    group_token_by_id: dict[str, str] = {
        gid: _normalize_group_token(name) for gid, name in group_name_by_id.items()
    }
    groups_payload = [
        {"id": gid, "name": group_name_by_id[gid]} for gid in group_name_by_id
    ]

    memberships_by_property: dict[str, list[str]] = {}
    for m in mem_rows:
        memberships_by_property.setdefault(str(m["property_id"]), []).append(
            str(m["property_group_id"])
        )

    items: list[dict] = []
    for p in prop_rows:
        pid = str(p["id"])
        community = str(p["community"] or "").strip()
        community_token = _normalize_group_token(community)
        member_ids = memberships_by_property.get(pid, [])

        # A property is "ok" if it has no community label (community is optional
        # decoration) OR if at least one of its memberships matches the community.
        community_is_meaningful = bool(community) and community.lower() != "other"
        matching_member = next(
            (
                gid
                for gid in member_ids
                if _tokens_match(community_token, group_token_by_id.get(gid, ""))
            ),
            None,
        )
        if not community_is_meaningful:
            continue  # no actionable community label; skip
        if matching_member is not None:
            continue  # community and a membership agree -> ok, omit

        # Does a group with a matching name even exist for this community?
        matching_group_id = next(
            (
                gid
                for gid, token in group_token_by_id.items()
                if _tokens_match(community_token, token)
            ),
            None,
        )

        if matching_group_id is None:
            classification = "community_no_group"
            suggested_group_id = None
        elif not member_ids:
            classification = "missing_membership"
            suggested_group_id = matching_group_id
        else:
            classification = "mismatched_membership"
            suggested_group_id = matching_group_id

        items.append(
            {
                "property_id": pid,
                "property_name": str(p["name"] or ""),
                "community": community,
                "classification": classification,
                "current_group_ids": member_ids,
                "current_group_names": [group_name_by_id.get(gid, "") for gid in member_ids],
                "suggested_group_id": suggested_group_id,
                "suggested_group_name": group_name_by_id.get(suggested_group_id, "")
                if suggested_group_id
                else "",
            }
        )

    items.sort(key=lambda it: (it["classification"], it["property_name"]))
    return JSONResponse({"count": len(items), "items": items, "groups": groups_payload})


async def _scope_target_belongs_to_tenant(
    db: AsyncSession,
    *,
    scope_type: str,
    scope_target_id: str,
    tenant_id: str,
) -> bool:
    """Verify the promotion target belongs to the caller's tenant.

    Defense-in-depth for multi-tenancy: the candidate itself is already verified
    as the tenant's (it comes from the tenant-scoped pending set), but the
    *destination* scope_target_id arrives in the request body. A crafted request
    could pass another tenant's property/group UUID. This re-checks ownership
    against the real tables before any scoped-knowledge write.

    - tenant scope: target IS the tenant id (already derived from auth) -> ok.
    - property scope: target must be a property row for this tenant.
    - property_group scope: target must be a property_groups row for this tenant.
    Fails closed (returns False) on any error or missing table.
    """
    if scope_type == "tenant":
        return scope_target_id == tenant_id

    try:
        if scope_type == "property":
            row = (
                await db.execute(
                    text(
                        """
                        SELECT 1
                        FROM properties
                        WHERE id = CAST(:target AS uuid)
                          AND tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"target": scope_target_id, "tid": tenant_id},
                )
            ).first()
            return row is not None

        if scope_type == "property_group":
            # Guard for environments predating migration 076.
            exists = (
                await db.execute(
                    text("SELECT to_regclass('public.property_groups') IS NOT NULL AS present")
                )
            ).scalar()
            if not exists:
                return False
            row = (
                await db.execute(
                    text(
                        """
                        SELECT 1
                        FROM property_groups
                        WHERE id = CAST(:target AS uuid)
                          AND tenant_id = CAST(:tid AS uuid)
                          AND is_active = TRUE
                        LIMIT 1
                        """
                    ),
                    {"target": scope_target_id, "tid": tenant_id},
                )
            ).first()
            return row is not None
    except Exception:
        logger.exception("[KnowledgeProposals] scope-target ownership check failed")
        return False

    return False
