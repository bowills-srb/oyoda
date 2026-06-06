from __future__ import annotations

import asyncio
from uuid import uuid4

from db.models.documents import DocumentModel
from scripts.fetch_guidebooks_api import (
    build_page_artifacts,
    classify_known_property_skip,
    classify_stop_condition,
    compute_content_hash,
    extract_guide_token,
    GuideFetchResponse,
    normalize_json_bytes,
    persist_guidebook_document,
)


class FakeStored:
    def __init__(self, key: str) -> None:
        self.key = key
        self.bucket = "bucket"
        self.version = 1


class FakeR2Client:
    def __init__(self) -> None:
        self.upload_calls = []

    async def upload_file(self, tenant_id, document_id, filename, content, *, content_type=None, version=None):
        self.upload_calls.append((tenant_id, document_id, filename, content, content_type, version))
        if version is None:
            return FakeStored(f"{tenant_id}/{document_id}/original/{filename}")
        return FakeStored(f"{tenant_id}/{document_id}/versions/{version}/{filename}")


class FakeSession:
    def __init__(self, latest=None):
        self.latest = latest
        self.added = []
        self.flushed = False

    async def scalar(self, _stmt):
        return self.latest

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True


def _sample_payload():
    return {
        "pages": [
            {
                "id": 3362,
                "title": "Welcome",
                "path": "guide",
                "render_type": "static",
                "sections": [
                    {
                        "id": 10,
                        "title": "About Property",
                        "order": 1,
                        "visible": True,
                        "render_type": "default",
                        "blocks": [
                            {
                                "id": 20,
                                "title": "About Property",
                                "order": 0,
                                "render_type": "home.about_note",
                                "data": "<p>Hello beach</p>",
                            },
                            {
                                "id": 21,
                                "title": "Reservation",
                                "order": 1,
                                "render_type": "widget.reservation_info",
                                "data": {"checkin_time": "16:00:00"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_extract_guide_token():
    assert extract_guide_token("https://guide.breezeway.io/8YJVrz00STc") == "8YJVrz00STc"


def test_classify_known_property_skip_for_home_guide_not_available():
    response = GuideFetchResponse(
        status=422,
        final_url="https://api.breezeway.io/public/guides/6YRphTYrDO8",
        content_type="application/json",
        body=b'{"description":"Home Guide is not available","error":"Bad request","fields":null,"status_code":422}',
    )

    assert classify_known_property_skip(response) == "guide_not_configured"
    assert classify_stop_condition(response) is None


def test_unknown_422_still_stops():
    response = GuideFetchResponse(
        status=422,
        final_url="https://api.breezeway.io/public/guides/bad",
        content_type="application/json",
        body=b'{"description":"Something else","error":"Bad request","status_code":422}',
    )

    stop_reason = classify_stop_condition(response)
    assert stop_reason is not None
    assert "Unexpected HTTP 422" in stop_reason


def test_build_page_artifacts_preserves_html_and_metadata():
    artifacts = build_page_artifacts(_sample_payload())

    assert len(artifacts) == 1
    page = artifacts[0]
    assert page["page_id"] == 3362
    assert "<p>Hello beach</p>" in page["html"]
    assert "<pre>" in page["html"]
    assert page["metadata"]["sections"][0]["blocks"][0]["render_type"] == "home.about_note"


def test_persist_guidebook_document_creates_first_version(monkeypatch):
    fake_client = FakeR2Client()
    monkeypatch.setattr("scripts.fetch_guidebooks_api.get_r2_client", lambda: fake_client)
    session = FakeSession()
    property_row = {"tenant_id": str(uuid4()), "property_id": str(uuid4())}
    payload = _sample_payload()

    row, stored_new, reused = asyncio.run(
        persist_guidebook_document(
            session,
            property_row=property_row,
            guide_token="8YJVrz00STc",
            payload=payload,
            content_hash=compute_content_hash(normalize_json_bytes(payload)),
        )
    )

    assert stored_new is True
    assert reused is False
    assert row.version_number == 1
    assert row.document_type == "guidebook_api"
    assert row.file_path.endswith("/original/api_response.json")
    assert session.flushed is True


def test_persist_guidebook_document_reuses_identical_hash():
    payload = _sample_payload()
    payload_hash = compute_content_hash(normalize_json_bytes(payload))
    latest = DocumentModel(
        tenant_id=uuid4(),
        property_id=uuid4(),
        document_group_id=uuid4(),
        scope_type="property",
        version_number=1,
        document_type="guidebook_api",
        filename="api_response.json",
        file_path="existing",
        storage_backend="r2",
        content_hash=payload_hash,
    )
    session = FakeSession(latest=latest)

    row, stored_new, reused = asyncio.run(
        persist_guidebook_document(
            session,
            property_row={"tenant_id": str(latest.tenant_id), "property_id": str(latest.property_id)},
            guide_token="8YJVrz00STc",
            payload=payload,
            content_hash=payload_hash,
        )
    )

    assert row is latest
    assert stored_new is False
    assert reused is True
