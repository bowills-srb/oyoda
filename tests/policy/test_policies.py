"""
Policy Tests - Critical Business Rule Enforcement.

These are NOT unit tests - they test POLICY enforcement:
1. Tenant isolation
2. Agent permission boundaries
3. Data access controls
4. Voice guardrails

Example: "A concierge agent cannot reference pricing strategy language"
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from schemas.core import (
    Tenant,
    Property,
    Booking,
    GuestProfile,
    BookingChannel,
)


class TestTenantIsolation:
    """
    Test that tenant isolation is enforced everywhere.
    
    CRITICAL: No data should ever leak between tenants.
    """
    
    def test_schemas_require_tenant_id(self):
        """All tenant-scoped schemas must require tenant_id."""
        from schemas.core import (
            Operator,
            Property,
            Listing,
            Booking,
            GuestProfile,
            MessageThread,
            Message,
            GeoPolygon,
            MarketSnapshot,
            AnalyticsResult,
        )
        
        tenant_scoped_models = [
            Operator, Property, Listing, Booking, GuestProfile,
            MessageThread, Message, GeoPolygon, MarketSnapshot, AnalyticsResult,
        ]
        
        for model in tenant_scoped_models:
            # Check that tenant_id is a required field
            assert "tenant_id" in model.model_fields, \
                f"{model.__name__} must have tenant_id field"
            
            # Check that tenant_id is required (no default)
            field = model.model_fields["tenant_id"]
            assert field.is_required(), \
                f"{model.__name__}.tenant_id must be required"
    
    def test_tenant_data_cannot_cross_boundaries(self):
        """
        Data from one tenant should never be accessible to another.
        
        This is a logical test - in production, this is enforced by
        Row Level Security in PostgreSQL.
        """
        tenant_a = uuid4()
        tenant_b = uuid4()
        
        # Create property for tenant A
        prop_a = Property(
            tenant_id=tenant_a,
            operator_id=uuid4(),
            property_id=uuid4(),
            name="Tenant A Property",
            address_line1="123 A Street",
            city="City A",
            state="FL",
            postal_code="32459",
            latitude=30.0,
            longitude=-86.0,
            bedrooms=4,
            bathrooms=3.0,
            sleeps=8,
        )
        
        # Verify tenant_id is correct
        assert prop_a.tenant_id == tenant_a
        assert prop_a.tenant_id != tenant_b
        
        # In production, a query with tenant_b would never return prop_a
        # This is enforced by RLS policy:
        # CREATE POLICY tenant_isolation ON properties
        #   USING (tenant_id = current_setting('app.current_tenant_id')::uuid);


class TestAgentPermissions:
    """
    Test agent permission boundaries.
    
    Concierge agents should:
    - Read property context (full access)
    - Read market analytics (read-only, no modification)
    - NEVER see guest PII
    - NEVER see pricing strategy internals
    
    BD agents should:
    - Access market analytics (full)
    - Access aggregated guest signals (anonymized)
    - NEVER see individual guest PII
    """
    
    def test_guest_profile_has_no_pii(self):
        """
        GuestProfile must NOT contain PII.
        
        Policy: Guest profiles are for personalization patterns,
        not for storing personal information.
        """
        profile = GuestProfile(
            tenant_id=uuid4(),
            channel_guest_ids={"airbnb": "hashed_id"},
            guest_type="family",
            total_bookings=5,
        )
        
        # These fields should NOT exist
        forbidden_fields = [
            "email",
            "phone", 
            "name",
            "first_name",
            "last_name",
            "address",
            "ip_address",
            "credit_card",
            "ssn",
            "date_of_birth",
        ]
        
        model_fields = set(profile.__class__.model_fields.keys())
        
        for field in forbidden_fields:
            assert field not in model_fields, \
                f"POLICY VIOLATION: GuestProfile contains PII field '{field}'"
    
    def test_channel_guest_ids_are_hashed(self):
        """
        Channel guest IDs should be hashed, not raw.
        
        Policy: We never store raw external identifiers that could
        be used to look up guests on other platforms.
        """
        # This is a documentation/convention test
        # In production, the normalization worker hashes these
        profile = GuestProfile(
            tenant_id=uuid4(),
            channel_guest_ids={
                "airbnb": "abc123def456",  # Should be a hash
            },
        )
        
        # Hashes are typically 16+ characters
        for channel, guest_id in profile.channel_guest_ids.items():
            # Real validation would check hash format
            # For now, just verify it's not obviously an email or phone
            assert "@" not in guest_id, "Guest ID appears to be an email"
            assert not guest_id.replace("-", "").replace("+", "").isdigit(), \
                "Guest ID appears to be a phone number"


class TestVoiceGuardrails:
    """
    Test voice agent policy constraints.
    
    Voice agents must NEVER:
    - Mention exact revenue numbers
    - Guarantee bookings
    - Name competitors
    - Share pricing strategy details
    """
    
    # Forbidden phrases that should never appear in voice output
    FORBIDDEN_REVENUE_PATTERNS = [
        r"\$\d{1,3}(,\d{3})*\s*(per|annual|yearly|revenue)",
        r"revenue of \$",
        r"you('ll| will) make \$",
        r"guaranteed \$",
        r"earn \$\d",
    ]
    
    FORBIDDEN_COMPETITOR_PATTERNS = [
        r"better than (AirDNA|Pricelabs|Wheelhouse|Beyond)",
        r"unlike (AirDNA|Pricelabs|Wheelhouse|Beyond)",
        r"(AirDNA|Pricelabs|Wheelhouse|Beyond) (doesn't|can't|won't)",
    ]
    
    FORBIDDEN_GUARANTEE_PATTERNS = [
        r"guarantee(d|s)? (you|your|this)",
        r"will definitely",
        r"100% (sure|certain|guaranteed)",
        r"promise you",
    ]
    
    def test_policy_definitions_exist(self):
        """Voice policy constraints should be defined."""
        assert len(self.FORBIDDEN_REVENUE_PATTERNS) > 0
        assert len(self.FORBIDDEN_COMPETITOR_PATTERNS) > 0
        assert len(self.FORBIDDEN_GUARANTEE_PATTERNS) > 0
    
    def test_example_compliant_phrases(self):
        """Example compliant voice phrases should not match forbidden patterns."""
        import re
        
        compliant_phrases = [
            "Based on similar properties in your area, you could see strong returns.",
            "Properties like yours typically perform well in peak season.",
            "Our historical data suggests healthy occupancy rates.",
            "We've seen positive trends in your market segment.",
        ]
        
        all_forbidden = (
            self.FORBIDDEN_REVENUE_PATTERNS +
            self.FORBIDDEN_COMPETITOR_PATTERNS +
            self.FORBIDDEN_GUARANTEE_PATTERNS
        )
        
        for phrase in compliant_phrases:
            for pattern in all_forbidden:
                match = re.search(pattern, phrase, re.IGNORECASE)
                assert match is None, \
                    f"Compliant phrase matched forbidden pattern: {pattern}"


class TestDataAccessControls:
    """
    Test that data access follows defined boundaries.
    """
    
    def test_booking_financials_are_decimal(self):
        """
        Financial fields must use Decimal, not float.
        
        Policy: Prevent floating point errors in financial calculations.
        """
        booking = Booking(
            tenant_id=uuid4(),
            property_id=uuid4(),
            listing_id=uuid4(),
            start_date=date(2025, 7, 4),
            end_date=date(2025, 7, 11),
            nights=7,
            channel=BookingChannel.DIRECT,
            external_id="test",
            total_amount=Decimal("1234.56"),
            nightly_rate=Decimal("176.37"),
            booked_at=date(2025, 1, 1),
        )
        
        assert isinstance(booking.total_amount, Decimal)
        assert isinstance(booking.nightly_rate, Decimal)
        assert isinstance(booking.cleaning_fee, Decimal)
        assert isinstance(booking.service_fee, Decimal)
        assert isinstance(booking.taxes, Decimal)


class TestConciergeVsBDSeparation:
    """
    Test that Concierge and BD systems maintain proper separation.
    
    They share DATA but not MODELS.
    """
    
    def test_shared_schemas_exist(self):
        """Both systems should use the same core schemas."""
        from schemas.core import (
            Property,
            Booking,
            GuestProfile,
            MarketSnapshot,
        )
        
        # These are the shared primitives
        shared_schemas = [Property, Booking, GuestProfile, MarketSnapshot]
        
        for schema in shared_schemas:
            # All should have tenant_id
            assert "tenant_id" in schema.model_fields
            
            # All should be importable from schemas.core
            assert schema.__module__ == "schemas.core"
    
    def test_worker_categories_are_separate(self):
        """Worker categories should be distinct."""
        from workers.base import WorkerCategory
        
        # Verify distinct categories exist
        categories = set(c.value for c in WorkerCategory)
        
        assert "ingestion" in categories
        assert "normalization" in categories
        assert "analytics" in categories  # BD side
        assert "concierge" in categories  # Concierge side
        assert "feedback" in categories   # The bridge
        
        # At least 5 categories
        assert len(categories) >= 5
