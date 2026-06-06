#!/usr/bin/env python3
"""
API-first Breezeway guidebook fetcher.

This script replaces the old browser-tab assumption with Breezeway's public
guide API. It persists the raw API response as the source document and stores
per-page HTML/metadata artifacts in R2 for downstream extraction work.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, request
from uuid import UUID

from sqlalchemy import select, text

from app.services.storage import R2StorageError, get_r2_client
from db.models.documents import DocumentModel
from scripts.db_session_standalone import dispose, get_standalone_session


LOGGER = logging.getLogger("fetch_guidebooks_api")
GUIDEBOOK_API_BASE = "https://api.breezeway.io/public/guides"
DEFAULT_USER_AGENT = "Oyvoda/1.0 guidebook-ingestion"
STOP_STATUSES = {401, 403, 429}


class GuideFetchStop(RuntimeError):
    """Raised when upstream conditions require stopping the run."""


@dataclass
class GuideFetchResponse:
    status: int
    final_url: str
    content_type: str
    body: bytes

    @property
    def is_json(self) -> bool:
        return "json" in (self.content_type or "").lower()


def _json_body(response: GuideFetchResponse) -> Optional[Dict[str, Any]]:
    if not response.is_json:
        return None
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Breezeway guidebooks via the public API.")
    parser.add_argument(
        "--index",
        default="scripts/output/unit_info_import/guidebook_index.jsonl",
        help="Guidebook index jsonl with unit_code and guidebook_url fields.",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/output/guidebooks_api",
        help="Local summary/output directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional number of properties to process.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.25,
        help="Delay between API requests.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header to send to Breezeway.",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Optional tenant_id override. Otherwise resolved from properties table.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def load_index(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            guidebook_url = (item.get("guidebook_url") or "").strip()
            unit_code = (item.get("unit_code") or item.get("property_external_id") or "").strip()
            if guidebook_url and unit_code:
                rows.append(
                    {
                        "unit_code": unit_code,
                        "guidebook_url": guidebook_url,
                        "address": (item.get("address") or "").strip(),
                        "community": (item.get("community") or "").strip(),
                    }
                )
    return rows


def extract_guide_token(url: str) -> str:
    match = re.match(r"^https://guide\.breezeway\.io/([^/?#]+)", (url or "").strip())
    if not match:
        raise ValueError(f"Unsupported guidebook URL: {url}")
    return match.group(1)


def normalize_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("_")[:120] or "unknown"


def summarize_render_types(pages: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for page in pages:
        for section in page.get("sections") or []:
            for block in section.get("blocks") or []:
                key = str(block.get("render_type") or "unknown")
                counts[key] = counts.get(key, 0) + 1
    return counts


def _extract_block_html(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("content"), str):
            return data["content"]
        if isinstance(data.get("html"), str):
            return data["html"]
        return f"<pre>{escape(json.dumps(data, indent=2, ensure_ascii=False))}</pre>"
    if isinstance(data, list):
        rendered = "".join(_extract_block_html(item) for item in data)
        return rendered or f"<pre>{escape(json.dumps(data, indent=2, ensure_ascii=False))}</pre>"
    return f"<pre>{escape(str(data))}</pre>"


def build_page_artifacts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for page in payload.get("pages") or []:
        sections_meta: List[Dict[str, Any]] = []
        html_parts: List[str] = [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            f"<title>{escape(str(page.get('title') or 'Guide Page'))}</title>",
            "</head>",
            "<body>",
            f"<h1>{escape(str(page.get('title') or 'Guide Page'))}</h1>",
        ]
        for section in page.get("sections") or []:
            section_title = str(section.get("title") or "")
            html_parts.append("<section>")
            if section_title:
                html_parts.append(f"<h2>{escape(section_title)}</h2>")
            blocks_meta: List[Dict[str, Any]] = []
            for block in section.get("blocks") or []:
                block_html = _extract_block_html(block.get("data"))
                block_title = str(block.get("title") or "")
                render_type = str(block.get("render_type") or "unknown")
                html_parts.append(
                    f'<article data-block-id="{escape(str(block.get("id") or ""))}" '
                    f'data-render-type="{escape(render_type)}">'
                )
                if block_title and block_title != section_title:
                    html_parts.append(f"<h3>{escape(block_title)}</h3>")
                html_parts.append(block_html or "<p></p>")
                html_parts.append("</article>")
                blocks_meta.append(
                    {
                        "id": block.get("id"),
                        "title": block_title,
                        "order": block.get("order"),
                        "render_type": render_type,
                    }
                )
            html_parts.append("</section>")
            sections_meta.append(
                {
                    "id": section.get("id"),
                    "title": section_title,
                    "order": section.get("order"),
                    "visible": section.get("visible"),
                    "render_type": section.get("render_type"),
                    "blocks": blocks_meta,
                }
            )
        html_parts.extend(["</body>", "</html>"])
        page_id = int(page.get("id"))
        artifacts.append(
            {
                "page_id": page_id,
                "title": str(page.get("title") or ""),
                "path": str(page.get("path") or ""),
                "render_type": str(page.get("render_type") or ""),
                "html": "\n".join(html_parts),
                "metadata": {
                    "page_id": page_id,
                    "title": str(page.get("title") or ""),
                    "order": page.get("order"),
                    "path": str(page.get("path") or ""),
                    "render_type": str(page.get("render_type") or ""),
                    "sections": sections_meta,
                },
            }
        )
    return artifacts


async def resolve_property_record(
    db,
    *,
    unit_code: str,
    guidebook_url: str,
    tenant_id_override: Optional[str],
) -> Optional[Dict[str, Any]]:
    property_cols = await table_columns(db, "properties")
    property_id_col = "property_id" if "property_id" in property_cols else ("id" if "id" in property_cols else None)
    guide_col = "property_guide_url" if "property_guide_url" in property_cols else ("guide_url" if "guide_url" in property_cols else None)
    if property_id_col is None or guide_col is None or "property_code" not in property_cols or "tenant_id" not in property_cols:
        raise RuntimeError("properties table is missing required guidebook columns")

    params: Dict[str, Any] = {
        "code": unit_code,
        "guidebook_url": guidebook_url,
    }
    filters = [
        "property_code = :code",
    ]
    if tenant_id_override:
        filters.append("tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = tenant_id_override
    filters.append(f"{guide_col} = :guidebook_url")
    order_cols: List[str] = []
    if "updated_at" in property_cols:
        order_cols.append("updated_at DESC NULLS LAST")
    if "created_at" in property_cols:
        order_cols.append("created_at DESC NULLS LAST")
    if not order_cols:
        order_cols.append("property_code")
    query = text(
        f"""
        SELECT
            {property_id_col} AS property_id,
            tenant_id,
            property_code,
            {guide_col} AS guidebook_url
        FROM properties
        WHERE {' AND '.join(filters)}
        ORDER BY {", ".join(order_cols)}
        LIMIT 1
        """
    )
    row = (await db.execute(query, params)).mappings().first()
    return dict(row) if row else None


async def table_columns(db, table_name: str) -> set[str]:
    rows = await db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return {str(item[0]) for item in rows.fetchall()}


def _request_headers(user_agent: str) -> Dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }


def fetch_guide_payload(
    guide_token: str,
    *,
    user_agent: str,
    timeout: float = 30.0,
) -> GuideFetchResponse:
    url = f"{GUIDEBOOK_API_BASE}/{guide_token}"
    req = request.Request(url, headers=_request_headers(user_agent))
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return GuideFetchResponse(
                status=getattr(resp, "status", 200),
                final_url=resp.geturl(),
                content_type=resp.headers.get("Content-Type", ""),
                body=body,
            )
    except error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return GuideFetchResponse(
            status=exc.code,
            final_url=exc.geturl(),
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            body=body,
        )


def decode_guide_payload(response: GuideFetchResponse) -> Dict[str, Any]:
    if not response.is_json:
        raise GuideFetchStop(
            f"Unexpected content type from Breezeway API: {response.content_type or 'unknown'}"
        )
    try:
        return json.loads(response.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GuideFetchStop("Breezeway API returned invalid JSON") from exc


def classify_known_property_skip(response: GuideFetchResponse) -> Optional[str]:
    if response.status != 422:
        return None
    body = _json_body(response) or {}
    if (
        body.get("error") == "Bad request"
        and body.get("description") == "Home Guide is not available"
    ):
        return "guide_not_configured"
    return None


def classify_stop_condition(response: GuideFetchResponse) -> Optional[str]:
    if classify_known_property_skip(response):
        return None
    if response.status in STOP_STATUSES:
        return f"HTTP {response.status} from Breezeway public guide API"
    if response.status >= 300 and response.status not in {404}:
        body = _json_body(response)
        if response.status == 422 and body:
            return (
                f"Unexpected HTTP 422 from Breezeway public guide API: "
                f"{json.dumps(body, ensure_ascii=False, sort_keys=True)}"
            )
        return f"Unexpected HTTP {response.status} from Breezeway public guide API"
    if response.status == 200 and not response.is_json:
        return f"Unexpected non-JSON content type {response.content_type or 'unknown'}"
    final_url = (response.final_url or "").lower()
    if "captcha" in final_url or "challenge" in final_url:
        return f"Suspicious redirect detected: {response.final_url}"
    body_prefix = response.body[:512].lower()
    if b"<html" in body_prefix and b"breezeway" not in body_prefix:
        return "HTML response received instead of JSON payload"
    return None


async def persist_guidebook_document(
    db,
    *,
    property_row: Dict[str, Any],
    guide_token: str,
    payload: Dict[str, Any],
    content_hash: str,
) -> tuple[DocumentModel, bool, bool]:
    tenant_id = str(property_row["tenant_id"])
    property_id = str(property_row["property_id"])
    filename = "api_response.json"
    document_row = await db.scalar(
        select(DocumentModel)
        .where(
            DocumentModel.tenant_id == UUID(tenant_id),
            DocumentModel.property_id == UUID(property_id),
            DocumentModel.scope_type == "property",
            DocumentModel.document_type == "guidebook_api",
            DocumentModel.filename == filename,
        )
        .order_by(DocumentModel.version_number.desc(), DocumentModel.uploaded_at.desc())
        .limit(1)
    )
    raw_json = normalize_json_bytes(payload)

    if document_row and document_row.content_hash == content_hash:
        return document_row, False, True

    if document_row:
        created = await document_row.create_version(
            db,
            raw_json,
            mime_type="application/json",
            uploaded_by="guidebook_api_fetcher",
            content_hash=content_hash,
            file_size=len(raw_json),
        )
        return created, True, False

    import uuid

    document_group_id = uuid.uuid4()
    stored = await get_r2_client().upload_file(
        tenant_id,
        str(document_group_id),
        filename,
        raw_json,
        content_type="application/json",
    )
    row = DocumentModel(
        tenant_id=UUID(tenant_id),
        property_id=UUID(property_id),
        document_group_id=document_group_id,
        scope_type="property",
        version_number=1,
        document_type="guidebook_api",
        filename=filename,
        file_path=stored.key,
        storage_backend="r2",
        file_size=len(raw_json),
        mime_type="application/json",
        content_hash=content_hash,
        upload_method="guidebook_fetch",
        extraction_status="processing",
        uploaded_by="guidebook_api_fetcher",
    )
    db.add(row)
    await db.flush()
    return row, True, False


async def persist_artifacts(
    document_row: DocumentModel,
    *,
    source_url: str,
    guide_token: str,
    payload: Dict[str, Any],
    page_artifacts: List[Dict[str, Any]],
    fetched_at: datetime,
) -> None:
    client = get_r2_client()
    tenant_id = str(document_row.tenant_id)
    document_id = str(document_row.document_group_id)

    manifest = {
        "guide_token": guide_token,
        "source_url": source_url,
        "fetched_at": fetched_at.isoformat(),
        "page_count": len(page_artifacts),
        "render_types": summarize_render_types(payload.get("pages") or []),
    }
    await client.upload_artifact(
        tenant_id,
        document_id,
        "guide_manifest.json",
        json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )
    for page_artifact in page_artifacts:
        page_id = page_artifact["page_id"]
        await client.upload_artifact(
            tenant_id,
            document_id,
            f"page_{page_id}.html",
            page_artifact["html"].encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )
        await client.upload_artifact(
            tenant_id,
            document_id,
            f"page_{page_id}.metadata.json",
            json.dumps(page_artifact["metadata"], indent=2, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    document_row.extracted_fields = {
        "fully_ingested_via_api": True,
        "ingestion_source": "breezeway_public_api",
        "guide_token": guide_token,
        "source_url": source_url,
        "pages": [artifact["metadata"] for artifact in page_artifacts],
        "render_types": summarize_render_types(payload.get("pages") or []),
        "captured_at": fetched_at.isoformat(),
    }
    document_row.extraction_status = "completed"
    document_row.extraction_error = None
    document_row.processed_at = fetched_at


async def process_row(
    db,
    row: Dict[str, str],
    *,
    tenant_id_override: Optional[str],
    user_agent: str,
) -> Dict[str, Any]:
    unit_code = row["unit_code"]
    guidebook_url = row["guidebook_url"]
    guide_token = extract_guide_token(guidebook_url)
    property_row = await resolve_property_record(
        db,
        unit_code=unit_code,
        guidebook_url=guidebook_url,
        tenant_id_override=tenant_id_override,
    )
    if not property_row:
        return {
            "unit_code": unit_code,
            "guide_token": guide_token,
            "status": "error",
            "error": "property_not_found",
        }

    response = fetch_guide_payload(guide_token, user_agent=user_agent)
    skip_reason = classify_known_property_skip(response)
    if skip_reason:
        return {
            "unit_code": unit_code,
            "guide_token": guide_token,
            "status": "skipped_no_guide",
            "error": skip_reason,
        }
    stop_reason = classify_stop_condition(response)
    if stop_reason:
        raise GuideFetchStop(stop_reason)
    if response.status == 404:
        return {
            "unit_code": unit_code,
            "guide_token": guide_token,
            "status": "error",
            "error": "http_404",
        }
    if response.status >= 500:
        await asyncio.sleep(2.0)
        retry = fetch_guide_payload(guide_token, user_agent=user_agent)
        stop_reason = classify_stop_condition(retry)
        if stop_reason:
            raise GuideFetchStop(stop_reason)
        if retry.status >= 500:
            return {
                "unit_code": unit_code,
                "guide_token": guide_token,
                "status": "error",
                "error": f"http_{retry.status}",
            }
        response = retry

    payload = decode_guide_payload(response)
    raw_json = normalize_json_bytes(payload)
    content_hash = compute_content_hash(raw_json)
    document_row, stored_new, reused_existing = await persist_guidebook_document(
        db,
        property_row=property_row,
        guide_token=guide_token,
        payload=payload,
        content_hash=content_hash,
    )
    page_artifacts = build_page_artifacts(payload)
    fetched_at = datetime.now(timezone.utc)
    if not reused_existing:
        await persist_artifacts(
            document_row,
            source_url=guidebook_url,
            guide_token=guide_token,
            payload=payload,
            page_artifacts=page_artifacts,
            fetched_at=fetched_at,
        )

    return {
        "unit_code": unit_code,
        "guide_token": guide_token,
        "status": "unchanged" if reused_existing else "fetched",
        "document_id": str(document_row.id),
        "document_group_id": str(document_row.document_group_id),
        "version_number": document_row.version_number,
        "page_count": len(page_artifacts),
        "render_types": summarize_render_types(payload.get("pages") or []),
        "stored_new_object": stored_new,
        "reused_existing": reused_existing,
        "content_hash": content_hash,
    }


async def run(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_index(index_path)
    if args.limit:
        rows = rows[: args.limit]
    summary: Dict[str, Any] = {
        "source_index": str(index_path.resolve()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "total_properties": len(rows),
        "fetched": 0,
        "unchanged": 0,
        "errored": 0,
        "reason_counts": {
            "fetched": 0,
            "unchanged": 0,
            "skipped_no_guide": 0,
            "skipped_other_error": 0,
        },
        "render_types": {},
        "results": [],
    }

    async with get_standalone_session() as db:
        for idx, row in enumerate(rows):
            if idx:
                await asyncio.sleep(args.delay_seconds)
            try:
                result = await process_row(
                    db,
                    row,
                    tenant_id_override=args.tenant_id,
                    user_agent=args.user_agent,
                )
            except GuideFetchStop as exc:
                LOGGER.error("Stopping guidebook fetch run: %s", exc)
                summary["stopped"] = str(exc)
                break
            except (R2StorageError, ValueError) as exc:
                result = {
                    "unit_code": row.get("unit_code"),
                    "guide_token": None,
                    "status": "skipped_other_error",
                    "error": str(exc),
                }

            status = result["status"]
            if status == "fetched":
                summary["fetched"] += 1
                summary["reason_counts"]["fetched"] += 1
            elif status == "unchanged":
                summary["unchanged"] += 1
                summary["reason_counts"]["unchanged"] += 1
            elif status == "skipped_no_guide":
                summary["errored"] += 1
                summary["reason_counts"]["skipped_no_guide"] += 1
            else:
                summary["errored"] += 1
                summary["reason_counts"]["skipped_other_error"] += 1
            for render_type, count in (result.get("render_types") or {}).items():
                summary["render_types"][render_type] = summary["render_types"].get(render_type, 0) + count
            summary["results"].append(result)
            LOGGER.info(
                "[GuidebookAPI] %s %s (%s)",
                row["unit_code"],
                status,
                result.get("guide_token") or "no-token",
            )

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if "stopped" not in summary else 2


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    try:
        return asyncio.run(run(args))
    finally:
        try:
            asyncio.run(dispose())
        except RuntimeError:
            pass


if __name__ == "__main__":
    sys.exit(main())
