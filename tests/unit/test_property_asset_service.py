from __future__ import annotations

import asyncio
import json

from app.services.operator.property_asset_service import OperatorPropertyAssetService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if not self.scripted:
            return _FakeMappingsResult([])
        kind, payload = self.scripted.pop(0)
        assert kind == "mappings"
        return _FakeMappingsResult(payload)

    async def scalar(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        kind, payload = self.scripted.pop(0)
        assert kind == "scalar"
        return payload


def test_upsert_asset_creates_new_asset_record():
    service = OperatorPropertyAssetService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", []),
            ("mappings", [{"asset_id": "asset-1"}]),
        ]
    )

    result = asyncio.run(
        service.upsert_asset(
            db,
            "00000000-0000-0000-0000-000000000001",
            property_code="LANIER-1",
            asset_type="hvac",
            asset_name="Main floor AC condenser",
            manufacturer="Carrier",
            serial_number="SER-123",
            install_vendor_name="Lanier HVAC",
            warranty_scope="parts",
            metadata={"seer_rating": "18"},
        )
    )

    assert result["asset_id"] == "asset-1"
    _, params = db.executed[-1]
    assert params["warranty_scope"] == "parts"
    assert json.loads(params["metadata_json"]) == {"seer_rating": "18"}


def test_list_assets_serializes_warranty_and_service_fields():
    service = OperatorPropertyAssetService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "asset_id": "asset-1",
                    "property_code": "LANIER-1",
                    "asset_type": "hvac",
                    "asset_name": "Main floor AC condenser",
                    "manufacturer": "Carrier",
                    "model_number": "ABC-1",
                    "serial_number": "SER-123",
                    "install_vendor_id": None,
                    "install_vendor_name": "Lanier HVAC",
                    "install_date": None,
                    "warranty_scope": "parts",
                    "warranty_provider": "Carrier",
                    "warranty_start_date": None,
                    "warranty_end_date": None,
                    "parts_warranty_end_date": None,
                    "labor_warranty_end_date": None,
                    "status": "active",
                    "condition_state": "good",
                    "useful_life_years": 12,
                    "last_service_at": None,
                    "last_work_order_id": None,
                    "notes": "Installed 2026 season",
                    "metadata_json": {"seer_rating": "18"},
                    "created_at": None,
                    "updated_at": None,
                }
            ]),
        ]
    )

    items = asyncio.run(
        service.list_assets(
            db,
            "00000000-0000-0000-0000-000000000001",
            "LANIER-1",
        )
    )

    assert len(items) == 1
    assert items[0]["asset_type"] == "hvac"
    assert items[0]["warranty_scope"] == "parts"
    assert items[0]["metadata"] == {"seer_rating": "18"}
