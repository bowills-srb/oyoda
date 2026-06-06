"""
Test Configuration and Fixtures.

Provides shared test infrastructure for:
- Unit tests
- Integration tests
- Policy tests

Testing Priorities (from blueprint):
1. Schema validation
2. Worker idempotency
3. Tenant isolation
4. Policy enforcement
"""

import asyncio
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Generator
from uuid import UUID, uuid4

import pytest

from schemas.core import (
    Tenant,
    Operator,
    Property,
    Listing,
    Booking,
    GuestProfile,
    MessageThread,
    Message,
    GeoPolygon,
    MarketSnapshot,
    BookingChannel,
    PropertyType,
)
from workers.base import InMemoryJobQueue, WorkerRegistry


# =============================================================================
# FIXTURES - Test Data Factories
# =============================================================================

@pytest.fixture
def tenant_id() -> UUID:
    """Generate a test tenant ID."""
    return uuid4()


@pytest.fixture
def operator_id() -> UUID:
    """Generate a test operator ID."""
    return uuid4()


@pytest.fixture
def property_id() -> UUID:
    """Generate a test property ID."""
    return uuid4()


@pytest.fixture
def sample_tenant(tenant_id: UUID) -> Tenant:
    """Create a sample tenant for testing."""
    return Tenant(
        tenant_id=tenant_id,
        name="Test Property Management Co",
        slug="test-pm-co",
        primary_email="test@example.com",
        timezone="America/Chicago",
        subscription_tier="growth",
    )


@pytest.fixture
def sample_operator(tenant_id: UUID, operator_id: UUID) -> Operator:
    """Create a sample operator for testing."""
    return Operator(
        tenant_id=tenant_id,
        operator_id=operator_id,
        name="Test Operator",
        code="TEST-001",
        markets_active=["30a-beaches", "destin"],
        property_count=25,
    )


@pytest.fixture
def sample_property(tenant_id: UUID, operator_id: UUID, property_id: UUID) -> Property:
    """Create a sample property for testing."""
    return Property(
        tenant_id=tenant_id,
        property_id=property_id,
        operator_id=operator_id,
        name="Sunset Beach House",
        address_line1="123 Beach Drive",
        city="Santa Rosa Beach",
        state="FL",
        postal_code="32459",
        latitude=30.3774,
        longitude=-86.2285,
        property_type=PropertyType.SINGLE_FAMILY,
        bedrooms=4,
        bathrooms=3.5,
        sleeps=10,
        square_footage=2800,
        has_pool=True,
        pool_heated=True,
        has_hot_tub=True,
        has_waterfront=True,
        waterfront_type="gulf",
        beach_access="private",
        pet_friendly=True,
    )


@pytest.fixture
def sample_listing(tenant_id: UUID, property_id: UUID) -> Listing:
    """Create a sample listing for testing."""
    return Listing(
        tenant_id=tenant_id,
        property_id=property_id,
        channel=BookingChannel.AIRBNB,
        external_id="airbnb-12345",
        title="Beautiful Gulf-Front Beach House with Private Pool",
        min_nights=3,
        max_guests=10,
    )


@pytest.fixture
def sample_booking(tenant_id: UUID, property_id: UUID) -> Booking:
    """Create a sample booking for testing."""
    listing_id = uuid4()
    return Booking(
        tenant_id=tenant_id,
        property_id=property_id,
        listing_id=listing_id,
        start_date=date(2025, 7, 4),
        end_date=date(2025, 7, 11),
        nights=7,
        adults=4,
        children=2,
        pets=True,
        channel=BookingChannel.AIRBNB,
        external_id="booking-abc123",
        total_amount=Decimal("3500.00"),
        nightly_rate=Decimal("450.00"),
        cleaning_fee=Decimal("250.00"),
        booked_at=datetime(2025, 3, 15, 10, 30),
    )


@pytest.fixture
def sample_polygon(tenant_id: UUID) -> GeoPolygon:
    """Create a sample geo polygon for testing."""
    return GeoPolygon(
        tenant_id=tenant_id,
        name="30A Beaches",
        geometry_type="Polygon",
        coordinates=[
            [
                [-86.5, 30.3],
                [-86.5, 30.4],
                [-86.0, 30.4],
                [-86.0, 30.3],
                [-86.5, 30.3],
            ]
        ],
        center_lat=30.35,
        center_lng=-86.25,
        bounds_north=30.4,
        bounds_south=30.3,
        bounds_east=-86.0,
        bounds_west=-86.5,
        polygon_type="market",
    )


# =============================================================================
# FIXTURES - Infrastructure
# =============================================================================

@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    """Create an in-memory job queue for testing."""
    return InMemoryJobQueue()


@pytest.fixture
def event_loop() -> Generator:
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_test_tenant(
    name: str = "Test Tenant",
    subscription_tier: str = "growth",
) -> Tenant:
    """Create a test tenant with custom attributes."""
    return Tenant(
        tenant_id=uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        primary_email=f"{name.lower().replace(' ', '.')}@test.com",
        subscription_tier=subscription_tier,
    )


def create_test_property(
    tenant_id: UUID,
    bedrooms: int = 4,
    has_pool: bool = True,
    **kwargs
) -> Property:
    """Create a test property with custom attributes."""
    defaults = {
        "property_id": uuid4(),
        "operator_id": uuid4(),
        "name": f"Test Property {bedrooms}BR",
        "address_line1": "123 Test St",
        "city": "Test City",
        "state": "FL",
        "postal_code": "32459",
        "latitude": 30.3774,
        "longitude": -86.2285,
        "property_type": PropertyType.SINGLE_FAMILY,
        "bedrooms": bedrooms,
        "bathrooms": bedrooms - 0.5,
        "sleeps": bedrooms * 2,
        "has_pool": has_pool,
    }
    defaults.update(kwargs)
    return Property(tenant_id=tenant_id, **defaults)


def create_test_booking(
    tenant_id: UUID,
    property_id: UUID,
    start_date: date,
    nights: int = 7,
    nightly_rate: Decimal = Decimal("300.00"),
    **kwargs
) -> Booking:
    """Create a test booking with custom attributes."""
    from datetime import timedelta
    
    end_date = start_date + timedelta(days=nights)
    defaults = {
        "listing_id": uuid4(),
        "start_date": start_date,
        "end_date": end_date,
        "nights": nights,
        "adults": 2,
        "children": 0,
        "channel": BookingChannel.DIRECT,
        "external_id": f"test-booking-{uuid4().hex[:8]}",
        "total_amount": nightly_rate * nights,
        "nightly_rate": nightly_rate,
        "booked_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return Booking(tenant_id=tenant_id, property_id=property_id, **defaults)


class _StubResultMappings:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _StubResult:
    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        mapping_rows: list[dict[str, Any]] | None = None,
    ):
        self._rows = rows or []
        self._mapping_rows = mapping_rows or []

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return _StubResultMappings(self._mapping_rows)


class StubDB:
    def __init__(self) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.case_key_index: dict[str, str] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.run_cases: dict[tuple[str, str], dict[str, Any]] = {}

    async def commit(self) -> None:
        return None

    async def execute(self, statement, params: dict[str, Any] | None = None):
        sql = str(statement)
        params = params or {}

        if "INSERT INTO brain_eval_cases" in sql:
            case_id = self.case_key_index.get(params["case_key"])
            now = datetime.now(timezone.utc)
            if case_id is None:
                case_id = str(uuid4())
                self.case_key_index[params["case_key"]] = case_id
                created_at = now
            else:
                created_at = self.cases[case_id]["created_at"]
            row = {
                "id": case_id,
                "case_key": params["case_key"],
                "message_text": params["message_text"],
                "market_tag": params["market_tag"],
                "source": params["source"],
                "expected_intent_topic": params["expected_intent_topic"],
                "expected_secondary_topics": list(params["expected_secondary_topics"]),
                "expected_sub_intents": list(params["expected_sub_intents"]),
                "expected_constraint_keys": list(params["expected_constraint_keys"]),
                "expected_review": params["expected_review"],
                "expected_urgency": params["expected_urgency"],
                "notes": params["notes"],
                "is_active": params["is_active"],
                "created_at": created_at,
                "updated_at": now,
            }
            self.cases[case_id] = row
            return _StubResult(rows=[(case_id,)])

        if "FROM brain_eval_cases" in sql and "WHERE is_active = TRUE" in sql:
            rows = [row for row in self.cases.values() if row["is_active"]]
            market_tag = params.get("market_tag")
            if market_tag:
                rows = [row for row in rows if row["market_tag"] == market_tag]
            case_keys = params.get("case_keys")
            if case_keys:
                allowed = set(case_keys)
                rows = [row for row in rows if row["case_key"] in allowed]
            rows.sort(key=lambda row: (row["market_tag"], row["case_key"]))
            return _StubResult(mapping_rows=[dict(row) for row in rows])

        if "INSERT INTO brain_eval_runs" in sql:
            run_id = str(uuid4())
            self.runs[run_id] = {
                "id": run_id,
                "invocation_id": params["invocation_id"],
                "classifier_source": params["classifier_source"],
                "market_filter": params["market_filter"],
                "notes": params["notes"],
                "status": "in_progress",
                "cases_evaluated": 0,
                "cases_passed": 0,
                "cases_failed": 0,
                "accuracy_overall": None,
                "accuracy_by_market": {},
                "run_started_at": datetime.now(timezone.utc),
                "run_completed_at": None,
            }
            return _StubResult(rows=[(run_id,)])

        if "UPDATE brain_eval_runs" in sql and "status             = 'completed'" in sql:
            run = self.runs[params["run_id"]]
            run["status"] = "completed"
            run["run_completed_at"] = datetime.now(timezone.utc)
            run["cases_evaluated"] = params["cases_evaluated"]
            run["cases_passed"] = params["cases_passed"]
            run["cases_failed"] = params["cases_failed"]
            run["accuracy_overall"] = params["accuracy_overall"]
            run["accuracy_by_market"] = json.loads(params["accuracy_by_market"])
            return _StubResult()

        if "UPDATE brain_eval_runs" in sql and "SET status = 'failed'" in sql:
            run = self.runs[params["run_id"]]
            run["status"] = "failed"
            run["run_completed_at"] = datetime.now(timezone.utc)
            error_note = params.get("error_note")
            if error_note:
                notes = run.get("notes") or ""
                run["notes"] = f"{notes}\n{error_note}" if notes else error_note
            return _StubResult()

        if "INSERT INTO brain_eval_run_cases" in sql:
            key = (params["run_id"], params["case_id"])
            self.run_cases[key] = {
                "run_id": params["run_id"],
                "case_id": params["case_id"],
                "passed": params["passed"],
                "failure_reasons": list(params["failure_reasons"]),
                "urgency_note": params["urgency_note"],
                "actual_intent_topic": params["actual_intent_topic"],
                "actual_secondary_topics": list(params["actual_secondary_topics"]),
                "actual_sub_intents": list(params["actual_sub_intents"]),
                "actual_review": params["actual_review"],
                "actual_urgency": params["actual_urgency"],
                "latency_ms": params["latency_ms"],
                "classifier_provider": params["classifier_provider"],
                "created_at": datetime.now(timezone.utc),
            }
            return _StubResult()

        if "FROM brain_eval_runs" in sql and "WHERE id = :run_id" in sql:
            run = self.runs.get(params["run_id"])
            if run is None:
                return _StubResult(mapping_rows=[])
            return _StubResult(mapping_rows=[dict(run)])

        if "FROM brain_eval_run_cases rc" in sql and "JOIN brain_eval_cases c" in sql:
            rows: list[dict[str, Any]] = []
            for (run_id, case_id), run_case in self.run_cases.items():
                if run_id != params["run_id"]:
                    continue
                case = self.cases[case_id]
                rows.append(
                    {
                        "case_key": case["case_key"],
                        "market_tag": case["market_tag"],
                        "passed": run_case["passed"],
                        "failure_reasons": list(run_case["failure_reasons"]),
                        "urgency_note": run_case["urgency_note"],
                    }
                )
            rows.sort(key=lambda row: (row["market_tag"], row["case_key"]))
            return _StubResult(mapping_rows=rows)

        raise NotImplementedError(f"StubDB.execute cannot handle SQL: {sql}")


@pytest.fixture
def stub_db() -> StubDB:
    return StubDB()
