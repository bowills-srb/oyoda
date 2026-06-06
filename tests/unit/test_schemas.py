"""
Unit Tests - Schema Validation.

Tests that schemas correctly validate data and enforce constraints.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.core import (
    Tenant,
    Property,
    Booking,
    GuestProfile,
    MarketSnapshot,
    BookingChannel,
    PropertyType,
    GuestType,
    SCHEMA_VERSION,
    get_schema_version,
)


class TestSchemaVersion:
    """Test schema versioning."""
    
    def test_schema_version_exists(self):
        """Schema version should be defined."""
        assert SCHEMA_VERSION is not None
        assert len(SCHEMA_VERSION) > 0
    
    def test_get_schema_version(self):
        """get_schema_version should return the version."""
        version = get_schema_version()
        assert version == SCHEMA_VERSION


class TestTenantSchema:
    """Test Tenant schema validation."""
    
    def test_valid_tenant(self, sample_tenant):
        """Valid tenant should pass validation."""
        assert sample_tenant.tenant_id is not None
        assert sample_tenant.name == "Test Property Management Co"
        assert sample_tenant.slug == "test-pm-co"
    
    def test_tenant_requires_name(self, tenant_id):
        """Tenant must have a name."""
        with pytest.raises(ValidationError):
            Tenant(
                tenant_id=tenant_id,
                name="",  # Empty name
                slug="test",
                primary_email="test@example.com",
            )
    
    def test_tenant_slug_format(self, tenant_id):
        """Tenant slug must match pattern."""
        with pytest.raises(ValidationError):
            Tenant(
                tenant_id=tenant_id,
                name="Test",
                slug="Invalid Slug!",  # Invalid characters
                primary_email="test@example.com",
            )
    
    def test_tenant_subscription_tiers(self, tenant_id):
        """Subscription tier must be valid."""
        for tier in ["starter", "growth", "enterprise"]:
            tenant = Tenant(
                tenant_id=tenant_id,
                name="Test",
                slug="test",
                primary_email="test@example.com",
                subscription_tier=tier,
            )
            assert tenant.subscription_tier == tier


class TestPropertySchema:
    """Test Property schema validation."""
    
    def test_valid_property(self, sample_property):
        """Valid property should pass validation."""
        assert sample_property.bedrooms == 4
        assert sample_property.has_pool is True
        assert sample_property.waterfront_type == "gulf"
    
    def test_property_bedroom_range(self, tenant_id):
        """Bedrooms must be within valid range."""
        # Valid range
        prop = Property(
            tenant_id=tenant_id,
            operator_id=uuid4(),
            property_id=uuid4(),
            name="Test",
            address_line1="123 Test",
            city="Test",
            state="FL",
            postal_code="32459",
            latitude=30.0,
            longitude=-86.0,
            bedrooms=10,
            bathrooms=8.0,
            sleeps=20,
        )
        assert prop.bedrooms == 10
        
        # Too many bedrooms
        with pytest.raises(ValidationError):
            Property(
                tenant_id=tenant_id,
                operator_id=uuid4(),
                property_id=uuid4(),
                name="Test",
                address_line1="123 Test",
                city="Test",
                state="FL",
                postal_code="32459",
                latitude=30.0,
                longitude=-86.0,
                bedrooms=100,  # Exceeds max
                bathrooms=8.0,
                sleeps=20,
            )
    
    def test_property_coordinates_range(self, tenant_id):
        """Coordinates must be valid lat/lng."""
        # Invalid latitude
        with pytest.raises(ValidationError):
            Property(
                tenant_id=tenant_id,
                operator_id=uuid4(),
                property_id=uuid4(),
                name="Test",
                address_line1="123 Test",
                city="Test",
                state="FL",
                postal_code="32459",
                latitude=100.0,  # Invalid
                longitude=-86.0,
                bedrooms=4,
                bathrooms=3.0,
                sleeps=8,
            )
        
        # Invalid longitude
        with pytest.raises(ValidationError):
            Property(
                tenant_id=tenant_id,
                operator_id=uuid4(),
                property_id=uuid4(),
                name="Test",
                address_line1="123 Test",
                city="Test",
                state="FL",
                postal_code="32459",
                latitude=30.0,
                longitude=-200.0,  # Invalid
                bedrooms=4,
                bathrooms=3.0,
                sleeps=8,
            )
    
    def test_property_state_length(self, tenant_id):
        """State must be 2 characters."""
        prop = Property(
            tenant_id=tenant_id,
            operator_id=uuid4(),
            property_id=uuid4(),
            name="Test",
            address_line1="123 Test",
            city="Test",
            state="FL",
            postal_code="32459",
            latitude=30.0,
            longitude=-86.0,
            bedrooms=4,
            bathrooms=3.0,
            sleeps=8,
        )
        assert len(prop.state) == 2


class TestBookingSchema:
    """Test Booking schema validation."""
    
    def test_valid_booking(self, sample_booking):
        """Valid booking should pass validation."""
        assert sample_booking.nights == 7
        assert sample_booking.adults == 4
        assert sample_booking.pets is True
    
    def test_booking_nights_positive(self, tenant_id, property_id):
        """Nights must be positive."""
        with pytest.raises(ValidationError):
            Booking(
                tenant_id=tenant_id,
                property_id=property_id,
                listing_id=uuid4(),
                start_date=date(2025, 7, 4),
                end_date=date(2025, 7, 11),
                nights=0,  # Invalid
                channel=BookingChannel.DIRECT,
                external_id="test",
                total_amount=Decimal("1000"),
                nightly_rate=Decimal("150"),
                booked_at=datetime.now(timezone.utc),
            )
    
    def test_booking_channels(self, tenant_id, property_id):
        """All booking channels should be valid."""
        for channel in BookingChannel:
            booking = Booking(
                tenant_id=tenant_id,
                property_id=property_id,
                listing_id=uuid4(),
                start_date=date(2025, 7, 4),
                end_date=date(2025, 7, 11),
                nights=7,
                channel=channel,
                external_id="test",
                total_amount=Decimal("1000"),
                nightly_rate=Decimal("150"),
                booked_at=datetime.now(timezone.utc),
            )
            assert booking.channel == channel
    
    def test_booking_amounts_non_negative(self, tenant_id, property_id):
        """Financial amounts must be non-negative."""
        # Total amount
        with pytest.raises(ValidationError):
            Booking(
                tenant_id=tenant_id,
                property_id=property_id,
                listing_id=uuid4(),
                start_date=date(2025, 7, 4),
                end_date=date(2025, 7, 11),
                nights=7,
                channel=BookingChannel.DIRECT,
                external_id="test",
                total_amount=Decimal("-100"),  # Invalid
                nightly_rate=Decimal("150"),
                booked_at=datetime.now(timezone.utc),
            )


class TestGuestProfileSchema:
    """Test GuestProfile schema validation."""
    
    def test_guest_profile_no_pii(self, tenant_id):
        """Guest profile should not contain PII fields."""
        profile = GuestProfile(
            tenant_id=tenant_id,
            channel_guest_ids={"airbnb": "hashed123"},
            guest_type=GuestType.FAMILY,
            total_bookings=5,
        )
        
        # Check no PII fields exist
        fields = profile.__class__.model_fields.keys()
        pii_fields = ["email", "phone", "name", "first_name", "last_name", "address"]
        for pii in pii_fields:
            assert pii not in fields, f"PII field '{pii}' should not exist"
    
    def test_guest_types(self, tenant_id):
        """All guest types should be valid."""
        for guest_type in GuestType:
            profile = GuestProfile(
                tenant_id=tenant_id,
                guest_type=guest_type,
            )
            assert profile.guest_type == guest_type


class TestMarketSnapshotSchema:
    """Test MarketSnapshot schema validation."""
    
    def test_valid_market_snapshot(self, tenant_id):
        """Valid market snapshot should pass validation."""
        snapshot = MarketSnapshot(
            tenant_id=tenant_id,
            polygon_id=uuid4(),
            snapshot_date=date.today(),
            period_type="daily",
            total_listings=100,
            active_listings=95,
            avg_occupancy=0.65,
            avg_adr=Decimal("250.00"),
            median_adr=Decimal("235.00"),
            adr_25th_percentile=Decimal("180.00"),
            adr_75th_percentile=Decimal("320.00"),
            total_revenue_period=Decimal("150000.00"),
            avg_revpar=Decimal("162.50"),
        )
        assert snapshot.avg_occupancy == 0.65
    
    def test_occupancy_range(self, tenant_id):
        """Occupancy must be between 0 and 1."""
        with pytest.raises(ValidationError):
            MarketSnapshot(
                tenant_id=tenant_id,
                polygon_id=uuid4(),
                snapshot_date=date.today(),
                period_type="daily",
                total_listings=100,
                active_listings=95,
                avg_occupancy=1.5,  # Invalid - over 100%
                avg_adr=Decimal("250.00"),
                median_adr=Decimal("235.00"),
                adr_25th_percentile=Decimal("180.00"),
                adr_75th_percentile=Decimal("320.00"),
                total_revenue_period=Decimal("150000.00"),
                avg_revpar=Decimal("162.50"),
            )
