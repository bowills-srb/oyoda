"""
Investment ROI & Scoring Module - Strategic Gap #5.

Platforms like Mashvisor focus on investment modeling.
We add signal-driven investment intelligence.

This module provides:
- ROI projections (not just ADR)
- Cap rate calculations
- Cash-on-cash returns
- Payback period analysis
- Investment dashboards leveraging signal architecture

Multi-persona appeal: Operators + Investors + Institutional Allocators
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals import (
    SignalBundle,
    SignalType,
    get_seasonality,
    get_amenity_lift,
    get_operator_delta,
)
from app.services.analytics.engine import (
    AnalyticsEngine,
    PropertyConfig,
    get_analytics_engine,
)


# =============================================================================
# INVESTMENT MODELS
# =============================================================================

class InvestmentStrategy(str, Enum):
    """Investment strategy types."""
    BUY_AND_HOLD = "buy_and_hold"
    VALUE_ADD = "value_add"
    FLIP = "flip"
    PORTFOLIO = "portfolio"


class RiskLevel(str, Enum):
    """Risk classification."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SPECULATIVE = "speculative"


@dataclass
class AcquisitionAssumptions:
    """Acquisition cost assumptions."""
    purchase_price: float
    closing_costs_pct: float = 0.03      # 3% of purchase
    renovation_budget: float = 0.0
    furnishing_budget: float = 0.0
    working_capital: float = 5000.0
    
    @property
    def total_investment(self) -> float:
        """Total cash required."""
        return (
            self.purchase_price * (1 + self.closing_costs_pct) +
            self.renovation_budget +
            self.furnishing_budget +
            self.working_capital
        )


@dataclass
class FinancingAssumptions:
    """Financing assumptions."""
    down_payment_pct: float = 0.25       # 25% down
    interest_rate: float = 0.07          # 7% annual
    loan_term_years: int = 30
    
    @property
    def ltv(self) -> float:
        """Loan-to-value ratio."""
        return 1 - self.down_payment_pct


@dataclass
class OperatingAssumptions:
    """Operating expense assumptions."""
    management_fee_pct: float = 0.20     # 20% of gross
    channel_fee_pct: float = 0.03        # 3% platform fees
    property_tax_annual: float = 5000.0
    insurance_annual: float = 2000.0
    utilities_monthly: float = 300.0
    maintenance_reserve_pct: float = 0.05  # 5% of gross
    vacancy_reserve_pct: float = 0.05    # 5% additional buffer


@dataclass
class CashFlowProjection:
    """Annual cash flow projection."""
    year: int
    
    # Revenue
    gross_rental_income: float
    other_income: float = 0.0
    
    # Operating expenses
    management_fees: float
    channel_fees: float
    property_taxes: float
    insurance: float
    utilities: float
    maintenance_reserve: float
    vacancy_reserve: float
    
    # Net Operating Income
    @property
    def total_operating_expenses(self) -> float:
        return (
            self.management_fees +
            self.channel_fees +
            self.property_taxes +
            self.insurance +
            self.utilities +
            self.maintenance_reserve +
            self.vacancy_reserve
        )
    
    @property
    def noi(self) -> float:
        """Net Operating Income."""
        return self.gross_rental_income + self.other_income - self.total_operating_expenses
    
    # Debt service (if financed)
    debt_service: float = 0.0
    
    @property
    def cash_flow_before_tax(self) -> float:
        """Cash flow before taxes."""
        return self.noi - self.debt_service


@dataclass
class InvestmentMetrics:
    """
    Investment performance metrics.
    
    These are the numbers institutional investors care about.
    """
    # Return metrics
    cap_rate: float                    # NOI / Purchase Price
    cash_on_cash_return: float         # Annual Cash Flow / Cash Invested
    gross_yield: float                 # Gross Income / Purchase Price
    
    # Payback
    payback_period_years: float        # Years to recover investment
    
    # 5-year projection
    total_cash_flow_5yr: float
    average_annual_return: float
    
    # IRR (if sufficient data)
    irr_5yr: Optional[float] = None
    
    # Risk-adjusted
    risk_adjusted_return: float = 0.0
    risk_level: RiskLevel = RiskLevel.MODERATE
    
    # Confidence
    confidence: float = 0.0


@dataclass
class InvestmentScore:
    """
    Overall investment score with signal attribution.
    
    Combines financial metrics with market intelligence.
    """
    # Overall score (0-100)
    score: int
    
    # Grade
    grade: str  # A, B, C, D, F
    
    # Component scores
    market_score: int           # Market fundamentals
    cash_flow_score: int        # Cash flow strength
    appreciation_score: int     # Growth potential
    risk_score: int             # Risk assessment
    
    # Key strengths
    strengths: List[str]
    
    # Key risks
    risks: List[str]
    
    # Recommendation
    recommendation: str
    
    # Confidence
    confidence: float


@dataclass
class InvestmentAnalysis:
    """
    Complete investment analysis.
    
    This is what goes in the BD deck for institutional allocators.
    """
    # Property
    property_id: Optional[UUID] = None
    geo_id: str = ""
    
    # Assumptions
    acquisition: AcquisitionAssumptions = None
    financing: FinancingAssumptions = None
    operating: OperatingAssumptions = None
    
    # Projections
    year_1_projection: CashFlowProjection = None
    year_5_projections: List[CashFlowProjection] = field(default_factory=list)
    
    # Metrics
    metrics: InvestmentMetrics = None
    
    # Score
    score: InvestmentScore = None
    
    # Signal attribution
    signal_drivers: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    computed_at: datetime = field(default_factory=datetime.utcnow)
    engine_version: str = "1.0.0"


# =============================================================================
# INVESTMENT ANALYSIS SERVICE
# =============================================================================

class InvestmentAnalysisService:
    """
    Investment Analysis Service.
    
    Provides signal-driven investment intelligence:
    - ROI projections
    - Cap rates
    - Cash-on-cash returns
    - Investment scoring
    
    All projections are based on signal-derived revenue forecasts.
    """
    
    def __init__(self):
        self.version = "1.0.0"
        self.analytics_engine = get_analytics_engine()
    
    def analyze_investment(
        self,
        signal_bundle: SignalBundle,
        property_config: PropertyConfig,
        acquisition: AcquisitionAssumptions,
        financing: Optional[FinancingAssumptions] = None,
        operating: Optional[OperatingAssumptions] = None,
    ) -> InvestmentAnalysis:
        """
        Run complete investment analysis.
        
        Uses signal-derived revenue projections to calculate:
        - Cap rate
        - Cash-on-cash return
        - Payback period
        - Investment score
        """
        financing = financing or FinancingAssumptions()
        operating = operating or OperatingAssumptions()
        
        # =================================================================
        # Step 1: Get revenue projection from signals
        # =================================================================
        revenue_result = self.analytics_engine.compute_revenue_projection(
            signal_bundle,
            property_config,
            output_type="bd_projection",
        )
        
        gross_revenue = revenue_result.gross_revenue_expected
        confidence = revenue_result.confidence
        
        # =================================================================
        # Step 2: Calculate Year 1 cash flow
        # =================================================================
        year_1 = self._calculate_annual_cash_flow(
            year=1,
            gross_revenue=gross_revenue,
            operating=operating,
            acquisition=acquisition,
            financing=financing,
        )
        
        # =================================================================
        # Step 3: Project 5 years (with growth assumptions)
        # =================================================================
        projections = [year_1]
        
        # Get growth signals
        momentum, _ = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM
        )
        base_growth = 0.03  # 3% base growth
        momentum_boost = (momentum or 0) * 0.02  # Up to 2% from momentum
        annual_growth = base_growth + momentum_boost
        
        current_revenue = gross_revenue
        for year in range(2, 6):
            current_revenue *= (1 + annual_growth)
            projection = self._calculate_annual_cash_flow(
                year=year,
                gross_revenue=current_revenue,
                operating=operating,
                acquisition=acquisition,
                financing=financing,
            )
            projections.append(projection)
        
        # =================================================================
        # Step 4: Calculate investment metrics
        # =================================================================
        metrics = self._calculate_metrics(
            acquisition=acquisition,
            financing=financing,
            year_1_cf=year_1,
            projections=projections,
            confidence=confidence,
        )
        
        # =================================================================
        # Step 5: Calculate investment score
        # =================================================================
        score = self._calculate_score(
            signal_bundle=signal_bundle,
            metrics=metrics,
            acquisition=acquisition,
        )
        
        # =================================================================
        # Step 6: Build signal attribution
        # =================================================================
        drivers = self._build_signal_drivers(signal_bundle, property_config)
        
        return InvestmentAnalysis(
            property_id=property_config.property_id if hasattr(property_config, 'property_id') else None,
            geo_id=signal_bundle.geo_id,
            acquisition=acquisition,
            financing=financing,
            operating=operating,
            year_1_projection=year_1,
            year_5_projections=projections,
            metrics=metrics,
            score=score,
            signal_drivers=drivers,
        )
    
    def _calculate_annual_cash_flow(
        self,
        year: int,
        gross_revenue: float,
        operating: OperatingAssumptions,
        acquisition: AcquisitionAssumptions,
        financing: FinancingAssumptions,
    ) -> CashFlowProjection:
        """Calculate cash flow for a single year."""
        
        # Operating expenses
        management_fees = gross_revenue * operating.management_fee_pct
        channel_fees = gross_revenue * operating.channel_fee_pct
        maintenance = gross_revenue * operating.maintenance_reserve_pct
        vacancy = gross_revenue * operating.vacancy_reserve_pct
        utilities = operating.utilities_monthly * 12
        
        # Debt service (if financed)
        debt_service = 0.0
        if financing.down_payment_pct < 1.0:
            loan_amount = acquisition.purchase_price * financing.ltv
            monthly_rate = financing.interest_rate / 12
            num_payments = financing.loan_term_years * 12
            
            # Monthly payment calculation
            if monthly_rate > 0:
                monthly_payment = loan_amount * (
                    monthly_rate * (1 + monthly_rate) ** num_payments
                ) / ((1 + monthly_rate) ** num_payments - 1)
                debt_service = monthly_payment * 12
        
        return CashFlowProjection(
            year=year,
            gross_rental_income=gross_revenue,
            management_fees=management_fees,
            channel_fees=channel_fees,
            property_taxes=operating.property_tax_annual,
            insurance=operating.insurance_annual,
            utilities=utilities,
            maintenance_reserve=maintenance,
            vacancy_reserve=vacancy,
            debt_service=debt_service,
        )
    
    def _calculate_metrics(
        self,
        acquisition: AcquisitionAssumptions,
        financing: FinancingAssumptions,
        year_1_cf: CashFlowProjection,
        projections: List[CashFlowProjection],
        confidence: float,
    ) -> InvestmentMetrics:
        """Calculate investment metrics."""
        
        # Cap rate = NOI / Purchase Price
        cap_rate = year_1_cf.noi / acquisition.purchase_price if acquisition.purchase_price > 0 else 0
        
        # Gross yield = Gross Income / Purchase Price
        gross_yield = year_1_cf.gross_rental_income / acquisition.purchase_price if acquisition.purchase_price > 0 else 0
        
        # Cash invested (down payment + other costs)
        cash_invested = (
            acquisition.purchase_price * financing.down_payment_pct +
            acquisition.purchase_price * acquisition.closing_costs_pct +
            acquisition.renovation_budget +
            acquisition.furnishing_budget +
            acquisition.working_capital
        )
        
        # Cash-on-cash = Annual Cash Flow / Cash Invested
        annual_cash_flow = year_1_cf.cash_flow_before_tax
        cash_on_cash = annual_cash_flow / cash_invested if cash_invested > 0 else 0
        
        # Payback period
        total_cf_5yr = sum(p.cash_flow_before_tax for p in projections)
        avg_cf = total_cf_5yr / 5 if projections else 0
        payback = cash_invested / avg_cf if avg_cf > 0 else float('inf')
        
        # Average annual return
        avg_return = avg_cf / cash_invested if cash_invested > 0 else 0
        
        # Risk-adjusted return (penalize for low confidence)
        risk_adjusted = avg_return * confidence
        
        # Risk level based on metrics
        if cap_rate > 0.08 and cash_on_cash > 0.10:
            risk_level = RiskLevel.LOW
        elif cap_rate > 0.06 and cash_on_cash > 0.06:
            risk_level = RiskLevel.MODERATE
        elif cap_rate > 0.04:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.SPECULATIVE
        
        return InvestmentMetrics(
            cap_rate=round(cap_rate, 4),
            cash_on_cash_return=round(cash_on_cash, 4),
            gross_yield=round(gross_yield, 4),
            payback_period_years=round(payback, 1),
            total_cash_flow_5yr=round(total_cf_5yr, 0),
            average_annual_return=round(avg_return, 4),
            risk_adjusted_return=round(risk_adjusted, 4),
            risk_level=risk_level,
            confidence=confidence,
        )
    
    def _calculate_score(
        self,
        signal_bundle: SignalBundle,
        metrics: InvestmentMetrics,
        acquisition: AcquisitionAssumptions,
    ) -> InvestmentScore:
        """Calculate overall investment score."""
        
        # Market score (from signals)
        seasonality = get_seasonality(signal_bundle)
        market_score = int(min(100, 50 + seasonality.confidence * 50))
        
        # Cash flow score (from metrics)
        cf_score = int(min(100, max(0, metrics.cash_on_cash_return * 500)))  # 20% CoC = 100
        
        # Appreciation score (placeholder - would use historical appreciation signals)
        appreciation_score = 60  # Default moderate
        
        # Risk score (inverse - higher is better)
        risk_map = {
            RiskLevel.LOW: 90,
            RiskLevel.MODERATE: 70,
            RiskLevel.HIGH: 50,
            RiskLevel.SPECULATIVE: 30,
        }
        risk_score = risk_map[metrics.risk_level]
        
        # Overall score (weighted average)
        overall = int(
            market_score * 0.25 +
            cf_score * 0.35 +
            appreciation_score * 0.20 +
            risk_score * 0.20
        )
        
        # Grade
        if overall >= 80:
            grade = "A"
        elif overall >= 70:
            grade = "B"
        elif overall >= 60:
            grade = "C"
        elif overall >= 50:
            grade = "D"
        else:
            grade = "F"
        
        # Strengths
        strengths = []
        if metrics.cap_rate > 0.07:
            strengths.append(f"Strong cap rate ({metrics.cap_rate:.1%})")
        if metrics.cash_on_cash_return > 0.10:
            strengths.append(f"Excellent cash-on-cash ({metrics.cash_on_cash_return:.1%})")
        if seasonality.confidence > 0.7:
            strengths.append("High market signal confidence")
        
        # Risks
        risks = []
        if metrics.confidence < 0.5:
            risks.append("Limited signal data - projections uncertain")
        if metrics.payback_period_years > 10:
            risks.append("Extended payback period")
        if metrics.risk_level == RiskLevel.SPECULATIVE:
            risks.append("High risk investment profile")
        
        # Recommendation
        if grade in ["A", "B"]:
            recommendation = "Strong investment candidate - proceed with due diligence"
        elif grade == "C":
            recommendation = "Moderate opportunity - review assumptions carefully"
        else:
            recommendation = "Below threshold - consider alternatives"
        
        return InvestmentScore(
            score=overall,
            grade=grade,
            market_score=market_score,
            cash_flow_score=cf_score,
            appreciation_score=appreciation_score,
            risk_score=risk_score,
            strengths=strengths,
            risks=risks,
            recommendation=recommendation,
            confidence=metrics.confidence,
        )
    
    def _build_signal_drivers(
        self,
        signal_bundle: SignalBundle,
        property_config: PropertyConfig,
    ) -> List[Dict[str, Any]]:
        """Build signal attribution for investment analysis."""
        
        drivers = []
        
        # Seasonality
        seasonality = get_seasonality(signal_bundle)
        if seasonality.has_signal:
            drivers.append({
                "signal": "seasonality",
                "value": seasonality.multiplier,
                "confidence": seasonality.confidence,
                "impact": f"{'Peak' if seasonality.multiplier > 1 else 'Off'} season factor",
            })
        
        # Amenity lift
        amenities = property_config.amenities if hasattr(property_config, 'amenities') else []
        lift = get_amenity_lift(signal_bundle, amenities)
        if lift.has_signals:
            drivers.append({
                "signal": "amenity_lift",
                "value": lift.multiplier,
                "confidence": lift.confidence,
                "impact": f"Amenities add {(lift.multiplier - 1) * 100:.0f}% premium",
            })
        
        # Operator delta
        operator = get_operator_delta(signal_bundle)
        if operator.has_signal:
            drivers.append({
                "signal": "operator_delta",
                "value": operator.applied_adr_delta,
                "confidence": operator.confidence,
                "impact": f"Operator performance {'above' if operator.applied_adr_delta > 0 else 'at'} market",
            })
        
        return drivers


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[InvestmentAnalysisService] = None


def get_investment_service() -> InvestmentAnalysisService:
    """Get investment analysis service singleton."""
    global _service
    if _service is None:
        _service = InvestmentAnalysisService()
    return _service


def analyze_investment(
    signal_bundle: SignalBundle,
    property_config: PropertyConfig,
    purchase_price: float,
    **kwargs,
) -> InvestmentAnalysis:
    """
    Analyze investment opportunity.
    
    Quick start function for investment analysis.
    """
    acquisition = AcquisitionAssumptions(purchase_price=purchase_price, **kwargs)
    return get_investment_service().analyze_investment(
        signal_bundle, property_config, acquisition
    )
