from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class YearlyEPS(BaseModel):
    year: int
    eps: Optional[float] = None

class FundamentalsResponse(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    current_price: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    total_current_assets: Optional[float] = None
    total_current_liabilities: Optional[float] = None
    working_capital: Optional[float] = None
    long_term_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    roe: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_rate: Optional[float] = None
    dividend_paying: bool
    eps_history: List[YearlyEPS]
    earnings_stability_pass: Optional[bool] = None
    earnings_growth_percent: Optional[float] = None
    graham_pe_pass: Optional[bool] = None
    graham_pb_pass: Optional[bool] = None
    graham_combined_pass: Optional[bool] = None
    long_term_debt_vs_working_capital_pass: Optional[bool] = None
    current_ratio_pass: Optional[bool] = None
    graham_summary_score: float
    graham_summary_label: str
    graham_number: Optional[float] = None
    explanation: str
    missing_fields: List[str]
    warnings: List[str]
    raw_data: Optional[Dict[str, Any]] = None

class ScanConfig(BaseModel):
    min_market_cap: float = Field(2_000_000_000, description="Minimum market cap in USD")
    min_current_ratio: float = Field(2.0, description="Minimum current ratio")
    require_long_term_debt_le_working_capital: bool = Field(True, description="Long-term debt <= working capital")
    require_positive_eps_history: bool = Field(True, description="Require positive EPS for all historical years available")
    eps_history_years: int = Field(10, description="Number of years of history to fetch")
    min_eps_growth_percent: float = Field(33.0, description="Minimum growth in EPS over history")
    max_trailing_pe: float = Field(15.0, description="Maximum trailing P/E ratio")
    max_price_to_book: float = Field(1.5, description="Maximum price to book ratio")
    max_pe_pb_product: float = Field(22.5, description="Maximum product of P/E and P/B (Graham multiplier)")
    require_dividend_paying: bool = Field(False, description="Require companies to currently pay dividends")
    require_positive_operating_cash_flow: bool = Field(False, description="Require positive operating cash flow")
    require_positive_free_cash_flow: bool = Field(False, description="Require positive free cash flow")
    allow_partial_data: bool = Field(True, description="Allow candidates with some missing data to pass if criteria met")
    min_pass_ratio: float = Field(0.7, description="Minimum check pass ratio to be classified as Strong")
    max_concurrency: int = Field(5, description="Maximum parallel HTTP fetches to Yahoo Finance")

class ScanRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "JNJ", "KO", "T"])
    config: Optional[ScanConfig] = Field(default_factory=ScanConfig)
    sort_by: str = Field("score", description="Sort by: 'score', 'pass_ratio', or 'market_cap'")
    descending: bool = Field(True, description="True for descending order")
    limit: int = Field(50, description="Limit of candidates returned")

class ScreenerResult(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    passed: bool
    score: float
    pass_ratio: float
    label: str
    reasons_passed: List[str]
    reasons_failed: List[str]
    missing_fields: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]

class ScanSummary(BaseModel):
    total_input: int
    total_processed: int
    total_passed: int
    total_failed: int
    total_insufficient_data: int

class ScanResponse(BaseModel):
    summary: ScanSummary
    results: List[ScreenerResult]
    top_candidates: List[str]
    failed_candidates: List[str]
    insufficient_data_candidates: List[str]
