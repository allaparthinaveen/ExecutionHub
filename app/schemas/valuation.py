from pydantic import BaseModel, Field
from typing import List, Optional

class ScreenUniverseRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "TSLA", "KO", "T"])
    stage: str = Field(..., description="Target life-cycle stage: 'young_growth', 'mature_value', or 'declining_turnaround'")

class ScreenerCandidate(BaseModel):
    ticker: str
    beta: Optional[float] = None
    fcf_yield: Optional[float] = None
    peg: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    operating_margin: Optional[float] = None
    margin_trend: Optional[float] = None
    score: float

class ScreenUniverseResponse(BaseModel):
    stage: str
    candidates: List[ScreenerCandidate]

class ValuationRequest(BaseModel):
    ticker: str = Field(..., example="AAPL")
    risk_free_rate_override: Optional[float] = Field(None, description="Risk-free rate as decimal (e.g. 0.04)")
    erp_override: Optional[float] = Field(None, description="Equity Risk Premium as decimal (e.g. 0.05)")
    cost_of_debt_override: Optional[float] = Field(None, description="Pre-tax Cost of Debt as decimal (e.g. 0.06)")
    growth_rate_override: Optional[float] = Field(None, description="High-growth stage growth rate as decimal (e.g. 0.12)")
    tax_rate_override: Optional[float] = Field(None, description="Corporate Tax rate as decimal (e.g. 0.25)")
    stable_growth_rate_override: Optional[float] = Field(None, description="Stable growth rate as decimal (e.g. 0.02)")

class DiscountRateDetails(BaseModel):
    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    cost_of_equity: float
    cost_of_debt: float
    tax_rate: float
    debt_to_equity: float
    equity_weight: float
    debt_weight: float
    wacc: float

class GrowthRateDetails(BaseModel):
    roc: float
    reinvestment_rate: float
    fundamental_growth_rate: float
    historical_revenue_cagr: float
    selected_growth_rate: float

class FCFFForecastYear(BaseModel):
    year: int
    fcff: float
    discount_factor: float
    present_value: float

class ValuationResponse(BaseModel):
    ticker: str
    current_price: float
    discount_rate_details: DiscountRateDetails
    growth_rate_details: GrowthRateDetails
    forecast: List[FCFFForecastYear]
    terminal_value: float
    present_value_terminal_value: float
    sum_pv_fcff: float
    enterprise_value: float
    cash: float
    debt: float
    equity_value: float
    shares_outstanding: float
    intrinsic_value: float
    valuation_conclusion: str
