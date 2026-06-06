from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.property_import_service import PropertyImportService


class _NoopSession:
    async def execute(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("session.execute should not be called in this unit test")

    async def commit(self):  # pragma: no cover
        return None


class _ReplayResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _ReplaySession:
    def __init__(self, row):
        self.row = row

    async def execute(self, *args, **kwargs):
        return _ReplayResult(self.row)

    async def commit(self):  # pragma: no cover
        return None


def test_tabular_import_preserves_unmapped_fields_in_extra_data():
    service = PropertyImportService(_NoopSession())

    record = service._tabular_prop_to_record(
        {
            "Unit Code": "178SC",
            "Name": "Sun Kissed",
            "Address": "178 Spartina Cir",
            "Beach Access Notes": "Private dune walkover",
            "Owner Special": "10% off seven nights",
        },
        operator_id="tenant-1",
        company_id="tenant-1",
        market_id="30a",
        source_label="dashboard_upload",
    )

    assert record["internal_code"] == "178SC"
    assert record["name"] == "Sun Kissed"
    assert record["extra_data"]["source"] == "dashboard_upload"
    assert record["extra_data"]["unmapped_fields"] == {
        "beach_access_notes": "Private dune walkover",
        "owner_special": "10% off seven nights",
    }

    diagnostics = record["__import_diagnostics"]
    assert "unit_code" in diagnostics["observed_columns"]
    assert diagnostics["unmapped_columns"] == ["beach_access_notes", "owner_special"]
    assert diagnostics["preserved_field_count"] == 2


def test_import_from_tabular_rows_reports_unmapped_column_coverage(monkeypatch):
    service = PropertyImportService(_NoopSession())

    async def _fake_upsert_property(self, record, pms_authoritative=False):
        return "prop-1", "inserted"

    async def _fake_index_property_to_vector(self, operator_id, db_id, record):
        return True

    class _Writer:
        async def register_property_record(self, *args, **kwargs):
            return None

    monkeypatch.setattr(PropertyImportService, "_upsert_property", _fake_upsert_property)
    monkeypatch.setattr(PropertyImportService, "_index_property_to_vector", _fake_index_property_to_vector)
    async def _fake_load_custom_mapping_profiles(self, operator_id):
        return {}
    monkeypatch.setattr(PropertyImportService, "_load_custom_mapping_profiles", _fake_load_custom_mapping_profiles)
    monkeypatch.setattr(
        "app.services.property_import_service.get_canonical_property_write_service",
        lambda db: _Writer(),
    )

    result = asyncio.run(
        service.import_from_tabular_rows(
            operator_id="tenant-1",
            company_id="tenant-1",
            market_id="30a",
            rows=[
                {
                    "Unit Code": "178SC",
                    "Name": "Sun Kissed",
                    "Address": "178 Spartina Cir",
                    "Beach Access Notes": "Private dune walkover",
                },
                {
                    "Unit Code": "65AS",
                    "Name": "Azalea Abbey",
                    "Address": "65 Azelea St",
                    "Portfolio Notes": "Owner blocks Labor Day",
                },
            ],
            source_label="dashboard_upload",
        )
    )

    assert result.inserted == 2
    assert result.vector_indexed == 2
    assert result.rows_with_unmapped_fields == 2
    assert result.preserved_field_count == 2
    assert result.unmapped_columns == ["beach_access_notes", "portfolio_notes"]
    assert "unit_code" in result.observed_columns


def test_tabular_import_maps_generic_provider_identity_fields():
    service = PropertyImportService(_NoopSession())

    record = service._tabular_prop_to_record(
        {
            "Provider": "escapia",
            "Provider Account ID": "2403",
            "Provider Property ID": "275114",
            "Provider Unit ID": "31Hickor",
            "Provider Listing ID": "listing-275114",
            "Name": "Sun Kissed on Hickory",
            "Address": "31 Hickory St",
        },
        operator_id="tenant-1",
        company_id="tenant-1",
        market_id="30a",
        source_label="dashboard_upload",
    )

    assert record["extra_data"]["provider_name"] == "escapia"
    assert record["extra_data"]["provider_account_id"] == "2403"
    assert record["extra_data"]["provider_property_id"] == "275114"
    assert record["extra_data"]["provider_unit_id"] == "31Hickor"
    assert record["extra_data"]["provider_listing_id"] == "listing-275114"
    assert {pair["ref_kind"]: pair["ref_value"] for pair in record["__canonical_ref_pairs"]} == {
        "provider_account_id": "2403",
        "property_id": "275114",
        "unit_id": "31Hickor",
        "listing_id": "listing-275114",
    }
    assert record["extra_data"]["mapping_profile"] == "dashboard_upload"


def test_owner_property_sheet_profile_maps_custom_columns():
    service = PropertyImportService(_NoopSession())

    record = service._tabular_prop_to_record(
        {
            "Home Name": "Sun Kissed on Hickory",
            "Street Address": "31 Hickory St",
            "Subdivision": "Seagrove",
            "Owner Notes": "Offer bikes and beach chairs.",
        },
        operator_id="tenant-1",
        company_id="tenant-1",
        market_id="30a",
        source_label="owner_property_sheet",
    )

    assert record["name"] == "Sun Kissed on Hickory"
    assert record["address_line1"] == "31 Hickory St"
    assert record["description"] == "Offer bikes and beach chairs."
    assert record["amenities"]["community"] == "Seagrove"
    assert record["extra_data"]["mapping_profile"] == "owner_property_sheet"
    assert record["__import_diagnostics"]["mapping_profile"] == "owner_property_sheet"


def test_custom_mapping_profile_can_override_builtin_aliases():
    service = PropertyImportService(_NoopSession())

    record = service._tabular_prop_to_record(
        {
            "Villa Label": "Dune Escape",
            "Street Alias": "14 Beach Rd",
        },
        operator_id="tenant-1",
        company_id="tenant-1",
        market_id="30a",
        source_label="custom_sheet",
        custom_profiles={
            "custom_sheet": {
                "property_name": ["villa_label"],
                "address1": ["street_alias"],
            }
        },
    )

    assert record["name"] == "Dune Escape"
    assert record["address_line1"] == "14 Beach Rd"
    assert record["extra_data"]["mapping_profile"] == "custom_sheet"


def test_resolve_mapping_profile_prefers_custom_profile_name():
    service = PropertyImportService(_NoopSession())

    profile = service._resolve_mapping_profile(
        {"provider_name": "mysterypms"},
        "custom_sheet",
        custom_profiles={"custom_sheet": {"property_name": ["villa_label"]}},
    )

    assert profile == "custom_sheet"


def test_pms_listing_record_emits_generic_provider_ref_pairs():
    service = PropertyImportService(_NoopSession())

    listing = SimpleNamespace(
        pms_provider="escapia",
        external_id="275114",
        provider_account_id="2403",
        provider_property_id="275114",
        provider_unit_id="31Hickor",
        provider_listing_id="listing-275114",
        provider_base_url="https://api.escapia.example",
        property_name="Sun Kissed on Hickory",
        address_line1="31 Hickory St",
        address_line2="",
        city="Santa Rosa Beach",
        state="FL",
        postal_code="32459",
        country="US",
        latitude=30.0,
        longitude=-86.0,
        bedrooms=4,
        bathrooms=3.0,
        square_footage=2000,
        property_type="single_family",
        has_pool=False,
        pool_heated=False,
        has_hot_tub=False,
        has_waterfront=False,
        waterfront_type=None,
        beach_access=None,
        pet_friendly=False,
        has_garage=False,
        has_ev_charger=False,
        has_game_room=False,
        has_home_theater=False,
        is_active=True,
        listing_status="active",
        description=None,
        wifi_network=None,
        wifi_password=None,
        door_code=None,
        gate_code=None,
        check_in_time=None,
        check_out_time=None,
    )

    record = service._pms_listing_to_record(
        listing,
        operator_id="tenant-1",
        company_id="tenant-1",
        market_id="30a",
    )

    assert record["extra_data"]["provider_account_id"] == "2403"
    assert record["extra_data"]["provider_property_id"] == "275114"
    assert record["extra_data"]["provider_unit_id"] == "31Hickor"
    assert record["extra_data"]["provider_listing_id"] == "listing-275114"
    assert {pair["ref_kind"]: pair["ref_value"] for pair in record["__canonical_ref_pairs"]} == {
        "provider_account_id": "2403",
        "property_id": "275114",
        "unit_id": "31Hickor",
        "listing_id": "listing-275114",
    }


def test_ingest_helpers_preserve_replayable_payload_shape():
    payload = {
        "rows": [{"property_id": "275114"}],
        "created_at": "2026-04-28T12:00:00",
    }
    assert PropertyImportService._infer_payload_row_count(payload) == 1
    assert PropertyImportService._coerce_jsonable(payload) == payload


def test_import_from_tabular_rows_records_ingest_event_id(monkeypatch):
    service = PropertyImportService(_NoopSession())

    async def _fake_upsert_property(self, record, pms_authoritative=False):
        return "prop-1", "inserted"

    async def _fake_index_property_to_vector(self, operator_id, db_id, record):
        return False

    async def _fake_record_ingest_event(self, **kwargs):
        return "ingest-123"

    class _Writer:
        async def register_property_record(self, *args, **kwargs):
            return None

    monkeypatch.setattr(PropertyImportService, "_upsert_property", _fake_upsert_property)
    monkeypatch.setattr(PropertyImportService, "_index_property_to_vector", _fake_index_property_to_vector)
    monkeypatch.setattr(PropertyImportService, "_record_ingest_event", _fake_record_ingest_event)
    async def _fake_load_custom_mapping_profiles(self, operator_id):
        return {}
    monkeypatch.setattr(PropertyImportService, "_load_custom_mapping_profiles", _fake_load_custom_mapping_profiles)
    monkeypatch.setattr(
        "app.services.property_import_service.get_canonical_property_write_service",
        lambda db: _Writer(),
    )

    result = asyncio.run(
        service.import_from_tabular_rows(
            operator_id="tenant-1",
            company_id="tenant-1",
            market_id="30a",
            rows=[{"Unit Code": "178SC", "Name": "Sun Kissed", "Address": "178 Spartina Cir"}],
            source_label="dashboard_upload",
        )
    )

    assert result.ingest_event_id == "ingest-123"
    assert result.mapping_profiles_used == ["dashboard_upload"]


def test_replay_ingest_event_uses_tabular_rows_payload(monkeypatch):
    service = PropertyImportService(
        _ReplaySession(
            {
                "source_type": "tabular_upload",
                "source_label": "owner_property_sheet",
                "payload": {"rows": [{"Home Name": "Dune Escape"}]},
            }
        )
    )

    async def _fake_import_from_tabular_rows(self, **kwargs):
        result = type("Result", (), {})()
        result.operator_id = kwargs["operator_id"]
        result.inserted = 1
        result.updated = 0
        result.vector_indexed = 0
        result.errors = []
        result.warnings = []
        result.property_ids = []
        result.observed_columns = []
        result.unmapped_columns = []
        result.rows_with_unmapped_fields = 0
        result.preserved_field_count = 0
        result.ingest_event_id = "replay-1"
        result.mapping_profiles_used = ["owner_property_sheet"]
        result.total = 1
        result.success = True
        return result

    monkeypatch.setattr(PropertyImportService, "import_from_tabular_rows", _fake_import_from_tabular_rows)

    result = asyncio.run(
        service.replay_ingest_event(
            ingest_event_id="11111111-1111-1111-1111-111111111111",
            operator_id="tenant-1",
            company_id="tenant-1",
            market_id="30a",
        )
    )

    assert result.ingest_event_id == "replay-1"
    assert result.mapping_profiles_used == ["owner_property_sheet"]


def test_replay_ingest_event_deserializes_pms_payload(monkeypatch):
    service = PropertyImportService(
        _ReplaySession(
            {
                "source_type": "pms_sync",
                "source_label": "pms_import",
                "payload": {"listings": [{"external_id": "275114", "provider_unit_id": "31Hickor"}]},
            }
        )
    )

    async def _fake_import_from_pms_listings(self, **kwargs):
        listings = kwargs["listings"]
        assert listings[0].external_id == "275114"
        assert listings[0].provider_unit_id == "31Hickor"
        result = type("Result", (), {})()
        result.operator_id = kwargs["operator_id"]
        result.inserted = 1
        result.updated = 0
        result.vector_indexed = 0
        result.errors = []
        result.warnings = []
        result.property_ids = []
        result.observed_columns = []
        result.unmapped_columns = []
        result.rows_with_unmapped_fields = 0
        result.preserved_field_count = 0
        result.ingest_event_id = "replay-pms"
        result.mapping_profiles_used = []
        result.total = 1
        result.success = True
        return result

    monkeypatch.setattr(PropertyImportService, "import_from_pms_listings", _fake_import_from_pms_listings)

    result = asyncio.run(
        service.replay_ingest_event(
            ingest_event_id="11111111-1111-1111-1111-111111111111",
            operator_id="tenant-1",
            company_id="tenant-1",
            market_id="30a",
        )
    )

    assert result.ingest_event_id == "replay-pms"
