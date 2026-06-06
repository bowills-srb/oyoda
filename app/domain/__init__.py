"""
Domain Layer - Pure Business Logic.

No FastAPI. No DB sessions. No external API calls.
Pure inputs → outputs.

This layer contains:
- Business entities (models)
- Business rules (computations)
- Domain logic (pure functions)

This layer does NOT contain:
- HTTP handlers
- Database access
- External API calls
- Framework dependencies

Domain Modules:
- signals: Signal models, bundles, confidence gating
- governance: Policy models, presets, evaluation
- pricing: Amenity uplifts, seasonality, sensitivity
- forecasting: Projections, reasoning, monthly breakdown
- ownership: Owner models, property linkage
- opportunity: HomeownerOpportunityScore, AssumptionProfile
- documents: PropertyEvidence, PropertyProfile
- market: MarketContext, EventCalendar, ExperienceDemand
- operations: OperationalState, decision rules
- concierge: GuestContext, ExperienceSuggestion, triggers
- bd: ProjectionScenario, NarrativeBlock, PitchBook

Architecture:
    ┌─────────────────────────────────────────────────┐
    │                   API Layer                      │
    │            (FastAPI, endpoints)                  │
    └─────────────────────┬───────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────┐
    │              Orchestration Layer                 │
    │   (IntelligenceRunner, OpportunityRunner,       │
    │    BDRunner, ConciergeRunner)                   │
    └─────────────────────┬───────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────┐
    │               Execution Layer                    │
    │   (Thin wrappers: DTO → domain → result)        │
    └─────────────────────┬───────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────┐
    │                Domain Layer                      │
    │   signals, governance, pricing, forecasting,    │
    │   ownership, opportunity, documents, market,    │
    │   operations, concierge, bd                     │
    │         *** PURE - NO IO ***                    │
    └─────────────────────────────────────────────────┘
"""

# =============================================================================
# DOMAIN PURITY GUARD
# =============================================================================

FORBIDDEN_MODULES = (
    "fastapi",
    "sqlalchemy", 
    "requests",
    "httpx",
    "aiohttp",
    "asyncpg",
    "psycopg2",
    "redis",
)


def _check_domain_purity():
    """
    Check that domain modules don't import forbidden IO modules.
    
    Returns list of violations (empty if pure).
    """
    import ast
    from pathlib import Path
    
    domain_root = Path(__file__).parent
    violations = []
    
    for py_file in domain_root.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
            
        try:
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(forbidden in alias.name for forbidden in FORBIDDEN_MODULES):
                            violations.append(f"{py_file.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(forbidden in node.module for forbidden in FORBIDDEN_MODULES):
                        violations.append(f"{py_file.name}: from {node.module}")
        except Exception:
            pass
    
    return violations


def assert_domain_purity():
    """
    Assert that the domain layer has no IO imports.
    
    Call this in tests:
        from app.domain import assert_domain_purity
        assert_domain_purity()  # Raises if violations found
    """
    violations = _check_domain_purity()
    if violations:
        raise RuntimeError(
            f"Domain layer purity violation! Found {len(violations)} forbidden imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Original modules
    "signals",
    "governance", 
    "pricing",
    "forecasting",
    
    # New modules (Phase 2)
    "ownership",
    "opportunity",
    "documents",
    "market",
    "operations",
    "concierge",
    "bd",
    
    # Purity check
    "assert_domain_purity",
]
