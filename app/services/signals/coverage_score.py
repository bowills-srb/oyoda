"""
Signal Coverage Score - The Killer BD Slide

This module calculates a comprehensive coverage score that demonstrates
data quality, freshness, and completeness to institutional partners.

The Coverage Score answers: "How confident can we be in this projection?"

Usage:
    calculator = CoverageScoreCalculator()
    score = calculator.calculate("30a", signals)
    
    # For BD deck
    print(f"Intelligence Grade: {score.intelligence_grade}")
    print(f"Assessment: {score.assessment}")
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math


# =============================================================================
# CONFIGURATION
# =============================================================================

class SignalCategory(str, Enum):
    """Categories for coverage calculation."""
    SUPPLY = "supply"
    DEMAND = "demand"
    PRICING = "pricing"
    AMENITY = "amenity"
    PLATFORM = "platform"
    SEASONALITY = "seasonality"
    MACRO = "macro"
    OPERATOR = "operator"


# Signal type to category mapping
SIGNAL_CATEGORIES = {
    # Supply
    "supply_density": SignalCategory.SUPPLY,
    "bedroom_distribution": SignalCategory.SUPPLY,
    "property_type_mix": SignalCategory.SUPPLY,
    
    # Demand
    "calendar_compression": SignalCategory.DEMAND,
    "lead_time": SignalCategory.DEMAND,
    "rate_acceleration": SignalCategory.DEMAND,
    
    # Pricing
    "rate_position": SignalCategory.PRICING,
    "rate_by_bedroom": SignalCategory.PRICING,
    
    # Amenity
    "amenity_prevalence": SignalCategory.AMENITY,
    "amenity_lift": SignalCategory.AMENITY,
    
    # Platform
    "platform_dominance": SignalCategory.PLATFORM,
    "platform_performance_bias": SignalCategory.PLATFORM,
    
    # Seasonality
    "seasonality": SignalCategory.SEASONALITY,
    "seasonality_curve": SignalCategory.SEASONALITY,
    
    # Macro
    "travel_flow": SignalCategory.MACRO,
    "event_impact": SignalCategory.MACRO,
    "weather_pattern": SignalCategory.MACRO,
    "housing_stock": SignalCategory.MACRO,
    "transaction_velocity": SignalCategory.MACRO,
    "regulatory_risk": SignalCategory.MACRO,
    
    # Operator (optional)
    "operator_delta": SignalCategory.OPERATOR,
    "operational_stability": SignalCategory.OPERATOR,
}

# Core signals required for high-confidence projections
CORE_SIGNALS = [
    "supply_density",
    "calendar_compression",
    "platform_dominance",
    "amenity_prevalence",
    "rate_position",
    "seasonality_curve",
]

# Category weights for overall score
CATEGORY_WEIGHTS = {
    SignalCategory.SUPPLY: 0.20,
    SignalCategory.DEMAND: 0.20,
    SignalCategory.PRICING: 0.20,
    SignalCategory.AMENITY: 0.10,
    SignalCategory.PLATFORM: 0.10,
    SignalCategory.SEASONALITY: 0.10,
    SignalCategory.MACRO: 0.10,
    SignalCategory.OPERATOR: 0.0,  # Optional, doesn't affect base score
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class CategoryCoverage:
    """Coverage metrics for a signal category."""
    category: SignalCategory
    signals_present: List[str]
    signals_expected: List[str]
    coverage_ratio: float
    avg_confidence: float
    avg_age_hours: float
    grade: str


@dataclass
class CoverageScore:
    """Complete coverage score for a market."""
    geo_id: str
    market_name: str
    calculated_at: datetime
    
    # Overall scores
    coverage_score: float  # 0-1
    coverage_grade: str    # A/B/C/D/F
    
    # Category breakdown
    supply_coverage: float
    demand_coverage: float
    pricing_coverage: float
    amenity_coverage: float
    platform_coverage: float
    seasonality_coverage: float
    macro_coverage: float
    
    category_details: Dict[str, CategoryCoverage] = field(default_factory=dict)
    
    # Signal inventory
    signals_present: List[str] = field(default_factory=list)
    signals_missing: List[str] = field(default_factory=list)
    core_signals_present: int = 0
    core_signals_total: int = len(CORE_SIGNALS)
    
    # Freshness metrics
    avg_signal_age_hours: float = 0.0
    oldest_signal_hours: float = 0.0
    newest_signal_hours: float = 0.0
    freshness_grade: str = "F"
    
    # Confidence metrics
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    confidence_grade: str = "F"
    
    # Combined grade
    intelligence_grade: str = "F"
    
    # Human-readable assessment
    assessment: str = ""
    assessment_details: List[str] = field(default_factory=list)
    
    # For BD slides
    slide_headline: str = ""
    slide_bullets: List[str] = field(default_factory=list)


# =============================================================================
# GRADE CALCULATOR
# =============================================================================

def score_to_grade(score: float) -> str:
    """Convert 0-1 score to letter grade."""
    if score >= 0.95:
        return "A+"
    elif score >= 0.90:
        return "A"
    elif score >= 0.85:
        return "A-"
    elif score >= 0.80:
        return "B+"
    elif score >= 0.75:
        return "B"
    elif score >= 0.70:
        return "B-"
    elif score >= 0.65:
        return "C+"
    elif score >= 0.60:
        return "C"
    elif score >= 0.55:
        return "C-"
    elif score >= 0.50:
        return "D"
    else:
        return "F"


def freshness_to_grade(avg_hours: float) -> str:
    """Convert average signal age to freshness grade."""
    if avg_hours <= 6:
        return "A+"
    elif avg_hours <= 12:
        return "A"
    elif avg_hours <= 24:
        return "A-"
    elif avg_hours <= 48:
        return "B"
    elif avg_hours <= 72:
        return "C"
    elif avg_hours <= 168:  # 1 week
        return "D"
    else:
        return "F"


def combine_grades(*grades: str) -> str:
    """Combine multiple grades into overall grade."""
    grade_values = {
        "A+": 4.3, "A": 4.0, "A-": 3.7,
        "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7,
        "D": 1.0, "F": 0.0,
    }
    
    values = [grade_values.get(g, 0) for g in grades]
    avg = sum(values) / len(values) if values else 0
    
    # Convert back to grade
    for grade, value in sorted(grade_values.items(), key=lambda x: -x[1]):
        if avg >= value - 0.15:
            return grade
    return "F"


# =============================================================================
# COVERAGE CALCULATOR
# =============================================================================

class CoverageScoreCalculator:
    """
    Calculates comprehensive signal coverage scores.
    
    This is the foundation for the "killer BD slide" that demonstrates
    data quality to institutional partners.
    """
    
    def __init__(self):
        self.signal_categories = SIGNAL_CATEGORIES
        self.core_signals = CORE_SIGNALS
        self.category_weights = CATEGORY_WEIGHTS
    
    def calculate(
        self,
        geo_id: str,
        signals: List[Dict],
        market_name: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> CoverageScore:
        """
        Calculate coverage score for a market.
        
        Args:
            geo_id: Market identifier
            signals: List of signal dicts
            market_name: Human-readable market name
            as_of: Point in time for calculation
            
        Returns:
            Complete CoverageScore with grades and assessment
        """
        as_of = as_of or datetime.utcnow()
        market_name = market_name or geo_id.replace("_", " ").title()
        
        # Initialize score
        score = CoverageScore(
            geo_id=geo_id,
            market_name=market_name,
            calculated_at=as_of,
            coverage_score=0.0,
            coverage_grade="F",
            supply_coverage=0.0,
            demand_coverage=0.0,
            pricing_coverage=0.0,
            amenity_coverage=0.0,
            platform_coverage=0.0,
            seasonality_coverage=0.0,
            macro_coverage=0.0,
        )
        
        if not signals:
            score.assessment = "No signals available. Data collection required."
            score.intelligence_grade = "F"
            return score
        
        # Extract signal types present
        signal_types = set()
        for s in signals:
            st = s.get("signal_type")
            if st:
                signal_types.add(st)
        
        score.signals_present = list(signal_types)
        
        # Calculate category coverage
        category_coverages = self._calculate_category_coverage(signals, as_of)
        score.category_details = {c.category.value: c for c in category_coverages}
        
        # Set category scores
        for cat in category_coverages:
            if cat.category == SignalCategory.SUPPLY:
                score.supply_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.DEMAND:
                score.demand_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.PRICING:
                score.pricing_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.AMENITY:
                score.amenity_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.PLATFORM:
                score.platform_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.SEASONALITY:
                score.seasonality_coverage = cat.coverage_ratio
            elif cat.category == SignalCategory.MACRO:
                score.macro_coverage = cat.coverage_ratio
        
        # Calculate core signal coverage
        core_present = [s for s in self.core_signals if s in signal_types]
        score.core_signals_present = len(core_present)
        score.signals_missing = [s for s in self.core_signals if s not in signal_types]
        
        # Calculate weighted overall coverage
        total_weight = sum(self.category_weights.values())
        weighted_sum = 0.0
        
        for cat in category_coverages:
            weight = self.category_weights.get(cat.category, 0)
            weighted_sum += cat.coverage_ratio * weight
        
        score.coverage_score = weighted_sum / total_weight if total_weight > 0 else 0
        score.coverage_grade = score_to_grade(score.coverage_score)
        
        # Calculate freshness metrics
        self._calculate_freshness_metrics(score, signals, as_of)
        
        # Calculate confidence metrics
        self._calculate_confidence_metrics(score, signals)
        
        # Calculate combined intelligence grade
        score.intelligence_grade = combine_grades(
            score.coverage_grade,
            score.freshness_grade,
            score.confidence_grade,
        )
        
        # Generate assessment
        self._generate_assessment(score)
        
        return score
    
    def _calculate_category_coverage(
        self,
        signals: List[Dict],
        as_of: datetime,
    ) -> List[CategoryCoverage]:
        """Calculate coverage for each signal category."""
        coverages = []
        
        # Group signals by category
        signals_by_cat: Dict[SignalCategory, List[Dict]] = {
            cat: [] for cat in SignalCategory
        }
        
        for signal in signals:
            signal_type = signal.get("signal_type")
            category = self.signal_categories.get(signal_type)
            if category:
                signals_by_cat[category].append(signal)
        
        # Calculate coverage per category
        for category in SignalCategory:
            cat_signals = signals_by_cat[category]
            
            # Get expected signals for this category
            expected = [
                st for st, cat in self.signal_categories.items()
                if cat == category
            ]
            
            # Get present signals
            present = list(set(
                s.get("signal_type") for s in cat_signals
                if s.get("signal_type")
            ))
            
            # Calculate metrics
            coverage_ratio = len(present) / len(expected) if expected else 0
            
            # Average confidence
            confidences = [s.get("confidence", 0) for s in cat_signals]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            # Average age
            ages = []
            for s in cat_signals:
                observed = s.get("observed_at")
                if observed:
                    if isinstance(observed, str):
                        observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
                    observed = observed.replace(tzinfo=None)
                    age_hours = (as_of - observed).total_seconds() / 3600
                    ages.append(age_hours)
            
            avg_age = sum(ages) / len(ages) if ages else float('inf')
            
            coverages.append(CategoryCoverage(
                category=category,
                signals_present=present,
                signals_expected=expected,
                coverage_ratio=coverage_ratio,
                avg_confidence=avg_confidence,
                avg_age_hours=avg_age,
                grade=score_to_grade(coverage_ratio),
            ))
        
        return coverages
    
    def _calculate_freshness_metrics(
        self,
        score: CoverageScore,
        signals: List[Dict],
        as_of: datetime,
    ):
        """Calculate freshness metrics."""
        ages = []
        
        for signal in signals:
            observed = signal.get("observed_at")
            if observed:
                if isinstance(observed, str):
                    observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
                observed = observed.replace(tzinfo=None)
                age_hours = (as_of - observed).total_seconds() / 3600
                ages.append(age_hours)
        
        if ages:
            score.avg_signal_age_hours = sum(ages) / len(ages)
            score.oldest_signal_hours = max(ages)
            score.newest_signal_hours = min(ages)
        else:
            score.avg_signal_age_hours = float('inf')
            score.oldest_signal_hours = float('inf')
            score.newest_signal_hours = float('inf')
        
        score.freshness_grade = freshness_to_grade(score.avg_signal_age_hours)
    
    def _calculate_confidence_metrics(
        self,
        score: CoverageScore,
        signals: List[Dict],
    ):
        """Calculate confidence metrics."""
        confidences = [s.get("confidence", 0) for s in signals if s.get("confidence")]
        
        if confidences:
            score.avg_confidence = sum(confidences) / len(confidences)
            score.min_confidence = min(confidences)
            score.max_confidence = max(confidences)
        else:
            score.avg_confidence = 0
            score.min_confidence = 0
            score.max_confidence = 0
        
        score.confidence_grade = score_to_grade(score.avg_confidence)
    
    def _generate_assessment(self, score: CoverageScore):
        """Generate human-readable assessment."""
        details = []
        bullets = []
        
        # Overall assessment
        if score.intelligence_grade in ["A+", "A", "A-"]:
            score.assessment = (
                f"High-confidence intelligence with {score.coverage_score:.0%} signal coverage. "
                f"Projections are production-ready with full attribution trail."
            )
            score.slide_headline = f"✅ {score.market_name}: Production-Ready Intelligence"
            
        elif score.intelligence_grade in ["B+", "B", "B-"]:
            score.assessment = (
                f"Good signal coverage ({score.coverage_score:.0%}) with some gaps. "
                f"Projections are reliable with noted limitations."
            )
            score.slide_headline = f"✅ {score.market_name}: Reliable Intelligence"
            
        elif score.intelligence_grade in ["C+", "C", "C-"]:
            score.assessment = (
                f"Moderate signal coverage ({score.coverage_score:.0%}). "
                f"Projections should be used with wider confidence bands."
            )
            score.slide_headline = f"⚠️ {score.market_name}: Moderate Coverage"
            
        else:
            score.assessment = (
                f"Insufficient signal coverage ({score.coverage_score:.0%}). "
                f"Additional data collection required before projections."
            )
            score.slide_headline = f"❌ {score.market_name}: Data Collection Needed"
        
        # Coverage details
        details.append(f"Overall Coverage: {score.coverage_score:.0%} ({score.coverage_grade})")
        bullets.append(f"{score.core_signals_present}/{score.core_signals_total} core signals present")
        
        # Freshness
        if score.avg_signal_age_hours < 24:
            details.append(f"Data Freshness: {score.avg_signal_age_hours:.1f}h avg ({score.freshness_grade})")
            bullets.append(f"Data updated within {score.avg_signal_age_hours:.0f} hours")
        else:
            details.append(f"Data Freshness: {score.avg_signal_age_hours/24:.1f}d avg ({score.freshness_grade})")
            bullets.append(f"⚠️ Data is {score.avg_signal_age_hours/24:.1f} days old")
        
        # Confidence
        details.append(f"Confidence: {score.avg_confidence:.0%} avg ({score.confidence_grade})")
        bullets.append(f"{score.avg_confidence:.0%} average signal confidence")
        
        # Missing signals
        if score.signals_missing:
            details.append(f"Missing: {', '.join(score.signals_missing)}")
            bullets.append(f"Missing signals: {', '.join(score.signals_missing)}")
        
        score.assessment_details = details
        score.slide_bullets = bullets


# =============================================================================
# BD SLIDE GENERATOR
# =============================================================================

class CoverageSlideGenerator:
    """
    Generates coverage score content for BD pitch decks.
    """
    
    def __init__(self):
        self.calculator = CoverageScoreCalculator()
    
    def generate_slide_content(
        self,
        score: CoverageScore,
    ) -> Dict[str, Any]:
        """
        Generate content for a BD pitch deck slide.
        
        Returns dict with all elements needed for the slide.
        """
        return {
            "headline": score.slide_headline,
            "grade_badge": {
                "grade": score.intelligence_grade,
                "label": "Intelligence Grade",
                "color": self._grade_color(score.intelligence_grade),
            },
            "score_ring": {
                "value": score.coverage_score,
                "label": "Signal Coverage",
                "display": f"{score.coverage_score:.0%}",
            },
            "category_bars": [
                {"label": "Supply", "value": score.supply_coverage, "color": "#3498db"},
                {"label": "Demand", "value": score.demand_coverage, "color": "#e74c3c"},
                {"label": "Pricing", "value": score.pricing_coverage, "color": "#27ae60"},
                {"label": "Amenity", "value": score.amenity_coverage, "color": "#9b59b6"},
                {"label": "Platform", "value": score.platform_coverage, "color": "#f39c12"},
                {"label": "Macro", "value": score.macro_coverage, "color": "#1abc9c"},
            ],
            "metrics": [
                {
                    "label": "Signals",
                    "value": f"{score.core_signals_present}/{score.core_signals_total}",
                    "sublabel": "core signals present",
                },
                {
                    "label": "Freshness",
                    "value": f"{score.avg_signal_age_hours:.0f}h",
                    "sublabel": "avg signal age",
                },
                {
                    "label": "Confidence",
                    "value": f"{score.avg_confidence:.0%}",
                    "sublabel": "avg signal confidence",
                },
            ],
            "bullets": score.slide_bullets,
            "assessment": score.assessment,
            "footnote": (
                f"Coverage calculated from {len(score.signals_present)} distinct signal types "
                f"as of {score.calculated_at.strftime('%b %d, %Y %H:%M UTC')}. "
                f"Core signals: supply, demand, pricing, amenity, platform, seasonality."
            ),
        }
    
    def _grade_color(self, grade: str) -> str:
        """Get color for grade badge."""
        if grade.startswith("A"):
            return "#27ae60"  # Green
        elif grade.startswith("B"):
            return "#3498db"  # Blue
        elif grade.startswith("C"):
            return "#f39c12"  # Orange
        else:
            return "#e74c3c"  # Red


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_coverage_score(
    geo_id: str,
    signals: List[Dict],
    market_name: Optional[str] = None,
) -> CoverageScore:
    """Calculate coverage score (convenience function)."""
    calculator = CoverageScoreCalculator()
    return calculator.calculate(geo_id, signals, market_name)


def generate_bd_slide_content(score: CoverageScore) -> Dict[str, Any]:
    """Generate BD slide content (convenience function)."""
    generator = CoverageSlideGenerator()
    return generator.generate_slide_content(score)
