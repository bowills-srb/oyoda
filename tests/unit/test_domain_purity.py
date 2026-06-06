"""
Tests for domain layer purity.

These tests ensure the domain layer remains free of IO dependencies.
Run with: pytest tests/unit/test_domain_purity.py -v
"""

import pytest


def test_domain_purity():
    """Domain layer should have zero forbidden imports."""
    from app.domain import assert_domain_purity
    
    # This will raise RuntimeError if any violations found
    assert_domain_purity()


def test_domain_imports_work():
    """Domain imports should work without IO dependencies."""
    # Signals
    from app.domain.signals import (
        Signal,
        SignalType,
        SignalBundle,
        compute_weighted_average,
        check_confidence_gate,
        OutputType,
    )
    
    # Governance
    from app.domain.governance import (
        DecisionPolicy,
        PolicyDecision,
        get_preset_policy,
    )
    
    # Pricing
    from app.domain.pricing import (
        AmenityType,
        compute_combined_amenity_uplift,
        compute_operator_delta,
    )
    
    # Forecasting
    from app.domain.forecasting import (
        PropertyInputs,
        MarketInputs,
        generate_projection,
    )
    
    # All imports should succeed
    assert Signal is not None
    assert DecisionPolicy is not None
    assert AmenityType is not None
    assert PropertyInputs is not None


def test_signal_computation_is_pure():
    """Signal computations should work without database."""
    from uuid import uuid4
    from app.domain.signals import (
        Signal,
        SignalType,
        SignalScope,
        SignalSource,
        SignalBundle,
        compute_weighted_average,
    )
    
    # Create signals (pure data)
    signal = Signal.create(
        tenant_id=uuid4(),
        signal_type=SignalType.SEASONALITY_CURVE,
        scope=SignalScope.GEO,
        value=1.25,
        confidence=0.85,
        source=SignalSource.INTERNAL_COMP,
        time_window="30d",
        geo_id="test-geo",
    )
    
    # Bundle is pure
    bundle = SignalBundle.from_signal_list(
        signals=[signal],
        geo_id="test-geo",
    )
    
    # Computation is pure
    result = compute_weighted_average([signal])
    
    assert result is not None
    assert bundle.signal_count == 1


def test_projection_is_pure():
    """Projection generation should work without database."""
    from uuid import uuid4
    from app.domain.forecasting import (
        PropertyInputs,
        MarketInputs,
        generate_projection,
    )
    from app.domain.pricing import AmenityType
    
    # Pure inputs
    property_inputs = PropertyInputs(
        bedrooms=4,
        bathrooms=3.5,
        amenities=[AmenityType.POOL],
    )
    
    market_inputs = MarketInputs(
        market_id=uuid4(),
        market_name="Test Market",
        median_adr_by_bedroom={4: 500},
        median_occupancy_by_bedroom={4: 0.50},
    )
    
    # Pure computation
    projection = generate_projection(
        property_inputs=property_inputs,
        market_inputs=market_inputs,
    )
    
    assert projection.projected_annual_revenue > 0
    assert len(projection.monthly_projections) == 12


def test_governance_is_pure():
    """Governance evaluation should work without database."""
    from app.domain.governance import (
        get_preset_policy,
        HealthGrade,
    )
    
    # Get policy (pure)
    policy = get_preset_policy("high_confidence_pricing")
    
    # Evaluate (pure)
    decision = policy.evaluate({
        "confidence": 0.85,
        "health_grade": HealthGrade.A,
    })
    
    assert decision.is_allowed()
