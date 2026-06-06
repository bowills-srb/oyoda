"""
Domain: Forecasting

Pure domain layer for revenue projections.

No FastAPI. No DB sessions. No external API calls.
"""

from .projections import (
    # Reasoning
    AppliedUplift,
    CompAnalysis,
    ProjectionReasoning,
    
    # Inputs
    PropertyInputs,
    MarketInputs,
    CompSet,
    OperatorInputs,
    
    # Outputs
    MonthlyProjection,
    AnnualProjection,
    
    # Engine
    generate_projection,
    ENGINE_VERSION,
)


__all__ = [
    # Reasoning
    "AppliedUplift",
    "CompAnalysis",
    "ProjectionReasoning",
    
    # Inputs
    "PropertyInputs",
    "MarketInputs",
    "CompSet",
    "OperatorInputs",
    
    # Outputs
    "MonthlyProjection",
    "AnnualProjection",
    
    # Engine
    "generate_projection",
    "ENGINE_VERSION",
]
