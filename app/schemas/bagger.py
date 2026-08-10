from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class BaggerFilterConfig(BaseModel):
    """Configuration thresholds for Christopher Mayer 100-bagger checks."""
    max_market_cap_inr: float = Field(
        50000000000.0, 
        description="Max market cap in INR. Default is 5,000 Crore INR (~$600M USD) to target small starting size."
    )
    max_market_cap_usd: float = Field(
        1500000000.0, 
        description="Max market cap in USD. Default is $1.5 Billion USD to target small starting size for US markets."
    )
    min_revenue_cagr: float = Field(
        15.0, 
        description="Minimum compound annual growth rate in sales/revenue (%)."
    )
    min_earnings_cagr: float = Field(
        15.0, 
        description="Minimum compound annual growth rate in EPS (%)."
    )
    min_roe: float = Field(
        15.0, 
        description="Minimum Return on Equity (%) for high compounding efficiency."
    )
    min_operating_margin: float = Field(
        10.0, 
        description="Minimum operating margin (%) representing pricing power / moat."
    )
    min_promoter_holding: float = Field(
        30.0, 
        description="Minimum promoter/insider holding (%) for skin in the game (India-specific)."
    )
    max_pe_ratio: float = Field(
        40.0, 
        description="Maximum trailing/forward PE ratio to filter out hyper-inflated valuations."
    )
    max_debt_to_equity: float = Field(
        1.0, 
        description="Maximum Debt-to-Equity ratio to enforce debt safety."
    )
    min_pass_ratio: float = Field(
        0.90, 
        description="Minimum fraction of evaluable checks that must pass. Default is 0.90 (90%)."
    )
    max_concurrency: int = Field(
        5, 
        description="Maximum number of parallel ticker queries allowed."
    )
    min_ocf_to_net_income_ratio: float = Field(
        0.80,
        description="Minimum ratio of Cash Flow from Operations to Net Income. Ensures profits are backed by real cash."
    )
    max_pledged_percentage: float = Field(
        10.0,
        description="Maximum percentage of promoter holdings that can be pledged. Enforces skin in the game."
    )

class YearlyMetric(BaseModel):
    """Historical yearly value for growth metrics."""
    year: int
    value: float

class StockMetrics(BaseModel):
    """Normalized structural metrics extracted for evaluation."""
    ticker: str
    company_name: Optional[str] = None
    currency: str = "INR"
    market_cap: Optional[float] = None
    current_price: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    roe: Optional[float] = None
    operating_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    promoter_holding: Optional[float] = None
    ocf_to_net_income_ratio: Optional[float] = None
    pledged_percentage: Optional[float] = None
    revenue_history: List[YearlyMetric] = []
    eps_history: List[YearlyMetric] = []
    roic_history: List[YearlyMetric] = []

class ScreenerCheckResult(BaseModel):
    """Evaluation output for a single filter check."""
    check_name: str
    passed: bool
    description: str
    weight: float
    achieved_weight: float

class BaggerCandidate(BaseModel):
    """Complete 100-bagger evaluation report for a ticker."""
    ticker: str
    company_name: Optional[str] = None
    passed: bool
    score: float = Field(..., description="Overall score between 0.0 and 100.0 based on check weights.")
    pass_ratio: float = Field(..., description="Fraction of checks passed relative to total evaluable checks.")
    label: str = Field(..., description="Classification: 'High Potential', 'Moderate Potential', 'Low Potential', or 'Insufficient Data'.")
    checks: List[ScreenerCheckResult]
    missing_fields: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]
    explanation: str
    
    # Extra quantitative and qualitative enhancements (optional, based on request headers)
    deprioritized: Optional[bool] = Field(None, description="Whether the candidate was flagged and deprioritized by extra quantitative filters.")
    quantitative_flags: Optional[List[str]] = Field(None, description="List of triggered warnings for extra quantitative filters.")
    qualitative_score: Optional[float] = Field(None, description="Detailed qualitative score out of 90 points.")
    qualitative_breakdown: Optional[Dict[str, float]] = Field(None, description="Breakdown of qualitative score categories.")
    composite_score: Optional[float] = Field(None, description="Composite score = quantitative base score + qualitative score (out of 190).")
    thesis_summary: Optional[str] = Field(None, description="Concise investment thesis focused on multi-decade compounding potential.")
    kill_risks: Optional[List[str]] = Field(None, description="List of primary kill risks surfaced for this company.")
    confidence_level: Optional[str] = Field(None, description="Overall conviction level: High, Medium, or Low.")

class ScanRequest(BaseModel):
    """Payload for POST /scan requests."""
    tickers: List[str] = Field(
        default=[], 
        description="Universe of tickers to scan (e.g. ['DELHIVERY', 'ZOMATO']). If empty, auto-scans smallest NSE companies."
    )
    config: Optional[BaggerFilterConfig] = Field(default_factory=BaggerFilterConfig)
    auto_limit: int = Field(
        20, 
        description="If tickers list is empty and use_db is False, limits the automatically fetched symbols list size to the smallest N stocks."
    )
    use_db: bool = Field(
        True, 
        description="If True and tickers is empty, reads scanned candidates directly from the database scan results table."
    )
    filter_potentials: bool = Field(
        True,
        description="If True, returns only 'High Potential' and 'Moderate Potential' candidates from the database."
    )

class ScanSummary(BaseModel):
    """High-level summary of the scanner run."""
    total_input: int
    total_processed: int
    total_passed: int
    total_failed: int
    total_insufficient_data: int

class ScanResponse(BaseModel):
    """Payload returned by POST /scan."""
    summary: ScanSummary
    candidates: List[BaggerCandidate] = Field(..., description="Ranked short-list of bagger candidates matching criteria.")
    failed_candidates: List[str]
    insufficient_data_candidates: List[str]

class BacktestCandidateResult(BaseModel):
    ticker: str
    company_name: str
    buy_price: float
    current_price: float
    multiple: float
    cagr: float
    allocated_amount: float
    final_value: float
    profit: float

class BacktestSummary(BaseModel):
    total_candidates: int
    total_investment: float
    final_value: float
    total_profit: float
    return_multiple: float
    cagr: float

class BacktestResponse(BaseModel):
    summary: BacktestSummary
    candidates: List[BacktestCandidateResult]
