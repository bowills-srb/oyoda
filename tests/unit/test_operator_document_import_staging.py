from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.api.v1.endpoints import operator_app
from app.services.documents.extractors.base import ExtractedField, ExtractionResult, FieldConfidence


@dataclass
class _FakeCandidate:
    candidate_id: object
    candidate_type: str
    confidence: float


@dataclass
class _FakePromotionResult:
    candidate_id: object
    review_status: str
    promoted_to_table: str | None
    promoted_to_id: object | None


class _FakeStagingService:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.candidates: dict[object, _FakeCandidate] = {}

    async def create_candidate(self, session, *, tenant_id, scope_type, scope_target_id, **payload):
        candidate = _FakeCandidate(
            candidate_id=uuid4(),
            candidate_type=payload["candidate_type"],
            confidence=float(payload["confidence"]),
        )
        self.created.append(
            {
                "tenant_id": tenant_id,
                "scope_type": scope_type,
                "scope_target_id": scope_target_id,
                **payload,
                "candidate_id": candidate.candidate_id,
            }
        )
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    async def auto_promote_eligible(self, session, tenant_id, reviewed_by_user_id=None, candidate_ids=None):
        results = []
        for candidate_id in candidate_ids or []:
            candidate = self.candidates[candidate_id]
            if candidate.confidence >= 0.95 and candidate.candidate_type in {"fact", "asset"}:
                promoted_to_table = (
                    "concierge_scoped_knowledge"
                    if candidate.candidate_type == "fact"
                    else "operator_property_assets"
                )
                results.append(
                    _FakePromotionResult(
                        candidate_id=candidate.candidate_id,
                        review_status="auto_promoted",
                        promoted_to_table=promoted_to_table,
                        promoted_to_id=uuid4(),
                    )
                )
        return {"auto_promoted": len(results), "results": results}


class _FakeDB:
    async def commit(self):
        return None


class _FakePipeline:
    def __init__(self, normalized, document_class: str = "house_manual"):
        self._normalized = normalized
        self._document_class = document_class

    def process(self, content, *, filename, document_type_hint, content_type):
        return {
            "normalized": self._normalized,
            "document_class": self._document_class,
            "classification_confidence": 0.97,
        }


def _make_field(name: str, value: object, confidence: FieldConfidence, source_text: str = "excerpt") -> ExtractedField:
    return ExtractedField(
        field_name=name,
        value=value,
        confidence=confidence,
        source_document_type="house_manual",
        source_text=source_text,
        source_page=1,
    )


@pytest.mark.asyncio
async def test_document_import_auto_promotes_high_confidence_fact(monkeypatch):
    staging = _FakeStagingService()
    db = _FakeDB()
    document_id = uuid4()
    group_id = uuid4()

    monkeypatch.setattr(operator_app, "_get_operator_context", _async_return({
        "tenant_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "email": "ops@example.com",
    }))
    monkeypatch.setattr(operator_app, "_load_property_record_for_code", _async_return({
        "property_code": "203WW",
        "property_id": str(uuid4()),
    }))
    monkeypatch.setattr(operator_app, "_persist_source_document", _async_return((
        SimpleNamespace(id=document_id, document_group_id=group_id, version_number=1, storage_backend="r2"),
        True,
        False,
    )))
    monkeypatch.setattr(operator_app, "_save_document_extraction", _async_return(None))
    monkeypatch.setattr("app.services.extraction.get_extraction_staging_service", lambda: staging)
    monkeypatch.setattr(
        "app.services.documents.normalization.get_pipeline",
        lambda: _FakePipeline(SimpleNamespace(raw_text="Parking instructions", text_length=20)),
    )
    monkeypatch.setattr(
        "app.services.documents.extract_document",
        lambda text, document_class, metadata=None: ExtractionResult(
            document_type="house_manual",
            fields=[_make_field("parking_rules", "Two spaces only", FieldConfidence.HIGH)],
        ),
    )

    upload = UploadFile(filename="manual.pdf", file=_bytes_file(b"manual"))
    upload.headers = {"content-type": "application/pdf"}
    payload = await operator_app.import_property_document_upload(
        request=object(),
        file=upload,
        document_type="house_manual",
        target="knowledge",
        scope="property",
        property_code="203WW",
        asset_type=None,
        asset_name=None,
        source_label="dashboard_document_upload",
        db=db,
    )

    assert payload["auto_promoted_count"] == 1
    assert payload["staged_for_review_count"] == 0
    assert payload["knowledge_result"]["auto_promoted_count"] == 1
    assert payload["asset_result"] is None
    assert payload["document_id"] == str(document_id)


@pytest.mark.asyncio
async def test_document_import_stages_medium_confidence_fact(monkeypatch):
    staging = _FakeStagingService()
    db = _FakeDB()

    monkeypatch.setattr(operator_app, "_get_operator_context", _async_return({
        "tenant_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "email": "ops@example.com",
    }))
    monkeypatch.setattr(operator_app, "_load_property_record_for_code", _async_return({
        "property_code": "203WW",
        "property_id": str(uuid4()),
    }))
    monkeypatch.setattr(operator_app, "_persist_source_document", _async_return((
        SimpleNamespace(id=uuid4(), document_group_id=uuid4(), version_number=1, storage_backend="r2"),
        True,
        False,
    )))
    monkeypatch.setattr(operator_app, "_save_document_extraction", _async_return(None))
    monkeypatch.setattr("app.services.extraction.get_extraction_staging_service", lambda: staging)
    monkeypatch.setattr(
        "app.services.documents.normalization.get_pipeline",
        lambda: _FakePipeline(SimpleNamespace(raw_text="Pool closes at 10", text_length=18)),
    )
    monkeypatch.setattr(
        "app.services.documents.extract_document",
        lambda text, document_class, metadata=None: ExtractionResult(
            document_type="house_manual",
            fields=[_make_field("pool_rules", "Closes at 10 PM", FieldConfidence.MEDIUM)],
        ),
    )

    upload = UploadFile(filename="manual.pdf", file=_bytes_file(b"manual"))
    upload.headers = {"content-type": "application/pdf"}
    payload = await operator_app.import_property_document_upload(
        request=object(),
        file=upload,
        document_type="house_manual",
        target="knowledge",
        scope="property",
        property_code="203WW",
        asset_type=None,
        asset_name=None,
        source_label="dashboard_document_upload",
        db=db,
    )

    assert payload["auto_promoted_count"] == 0
    assert payload["staged_for_review_count"] == 1
    assert len(payload["staged_candidate_ids"]) == 1


@pytest.mark.asyncio
async def test_document_import_both_routes_knowledge_and_asset(monkeypatch):
    staging = _FakeStagingService()
    db = _FakeDB()

    monkeypatch.setattr(operator_app, "_get_operator_context", _async_return({
        "tenant_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "email": "ops@example.com",
    }))
    monkeypatch.setattr(operator_app, "_load_property_record_for_code", _async_return({
        "property_code": "203WW",
        "property_id": str(uuid4()),
    }))
    monkeypatch.setattr(operator_app, "_persist_source_document", _async_return((
        SimpleNamespace(id=uuid4(), document_group_id=uuid4(), version_number=1, storage_backend="r2"),
        True,
        False,
    )))
    monkeypatch.setattr(operator_app, "_save_document_extraction", _async_return(None))
    monkeypatch.setattr("app.services.extraction.get_extraction_staging_service", lambda: staging)
    monkeypatch.setattr(
        "app.services.documents.normalization.get_pipeline",
        lambda: _FakePipeline(SimpleNamespace(raw_text="Washer manual", text_length=13)),
    )
    monkeypatch.setattr(
        "app.services.documents.extract_document",
        lambda text, document_class, metadata=None: ExtractionResult(
            document_type="house_manual",
            fields=[_make_field("appliance_notes", "Front-load washer", FieldConfidence.HIGH)],
        ),
    )

    upload = UploadFile(filename="washer.pdf", file=_bytes_file(b"manual"))
    upload.headers = {"content-type": "application/pdf"}
    payload = await operator_app.import_property_document_upload(
        request=object(),
        file=upload,
        document_type="appliance_manual",
        target="both",
        scope="property",
        property_code="203WW",
        asset_type="appliance",
        asset_name="Washer",
        source_label="dashboard_document_upload",
        db=db,
    )

    assert payload["auto_promoted_count"] == 2
    assert payload["knowledge_result"]["auto_promoted_count"] == 1
    assert payload["asset_result"]["asset_id"]
    assert payload["staged_for_review_count"] == 0


@pytest.mark.asyncio
async def test_guest_qa_document_routes_through_scoped_import_path(monkeypatch):
    staging = _FakeStagingService()
    db = _FakeDB()
    guest_calls: list[dict] = []

    monkeypatch.setattr(operator_app, "_get_operator_context", _async_return({
        "tenant_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "email": "ops@example.com",
    }))
    monkeypatch.setattr(operator_app, "_load_property_record_for_code", _async_return({
        "property_code": "203WW",
        "property_id": str(uuid4()),
    }))
    monkeypatch.setattr(operator_app, "_persist_source_document", _async_return((
        SimpleNamespace(id=uuid4(), document_group_id=uuid4(), version_number=1, storage_backend="r2"),
        True,
        False,
    )))
    monkeypatch.setattr(operator_app, "_save_document_extraction", _async_return(None))
    monkeypatch.setattr("app.services.extraction.get_extraction_staging_service", lambda: staging)
    monkeypatch.setattr(
        "app.services.documents.normalization.get_pipeline",
        lambda: _FakePipeline(SimpleNamespace(raw_text="Q&A", text_length=3), document_class="guest_qa"),
    )
    monkeypatch.setattr(
        "app.services.documents.extract_document",
        lambda text, document_class, metadata=None: ExtractionResult(
            document_type="guest_qa",
            fields=[
                _make_field("guest_qa_record", {"question": "Is parking free?", "answer": "Yes"}, FieldConfidence.HIGH),
                _make_field("parking_rules", "Two spaces", FieldConfidence.HIGH),
            ],
        ),
    )

    async def _fake_guest_qa(*args, **kwargs):
        guest_calls.append(kwargs)
        return {"imported_answers": 1, "imported_gaps": 0, "skipped": 0, "total_records": 1}

    monkeypatch.setattr(operator_app, "_import_guest_qa_records", _fake_guest_qa)

    upload = UploadFile(filename="guest-qa.pdf", file=_bytes_file(b"qa"))
    upload.headers = {"content-type": "application/pdf"}
    payload = await operator_app.import_property_document_upload(
        request=object(),
        file=upload,
        document_type="guest_qa",
        target="knowledge",
        scope="property",
        property_code="203WW",
        asset_type=None,
        asset_name=None,
        source_label="dashboard_document_upload",
        db=db,
    )

    assert payload["guest_qa_result"]["imported_answers"] == 1
    assert len(guest_calls) == 1
    assert payload["auto_promoted_count"] == 1
    assert len(staging.created) == 1
    assert staging.created[0]["candidate_type"] == "fact"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _bytes_file(content: bytes):
    from io import BytesIO

    return BytesIO(content)
