"""
Domain: Pricing

Pure domain layer for pricing computations.

No FastAPI. No DB sessions. No external API calls.
"""

from .computations import (
    # Amenities
    AmenityType,
    AmenityUplift,
    DEFAULT_AMENITY_UPLIFTS,
    get_amenity_uplift,
    compute_combined_amenity_uplift,
    
    # Seasonality
    SeasonalityProfile,
    DEFAULT_COASTAL_SEASONALITY,
    DEFAULT_URBAN_SEASONALITY,
    get_default_seasonality,
    
    # Operator delta
    OperatorDelta,
    compute_operator_delta,
    apply_operator_delta_conservatively,
    
    # New listing
    compute_new_listing_penalty,
    
    # Discount
    DiscountResult,
    compute_recommended_discount,
    
    # Sensitivity
    PricingScenario,
    SensitivityResult,
    compute_pricing_sensitivity,
)


__all__ = [
    # Amenities
    "AmenityType",
    "AmenityUplift",
    "DEFAULT_AMENITY_UPLIFTS",
    "get_amenity_uplift",
    "compute_combined_amenity_uplift",
    
    # Seasonality
    "SeasonalityProfile",
    "DEFAULT_COASTAL_SEASONALITY",
    "DEFAULT_URBAN_SEASONALITY",
    "get_default_seasonality",
    
    # Operator delta
    "OperatorDelta",
    "compute_operator_delta",
    "apply_operator_delta_conservatively",
    
    # New listing
    "compute_new_listing_penalty",
    
    # Discount
    "DiscountResult",
    "compute_recommended_discount",
    
    # Sensitivity
    "PricingScenario",
    "SensitivityResult",
    "compute_pricing_sensitivity",
]
