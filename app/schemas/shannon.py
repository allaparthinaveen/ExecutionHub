from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class DeployStrategyRequest(BaseModel):
    asset_a: str = Field(..., example="NIFTYBEES-EQ")
    asset_b: str = Field(..., example="GOLDBEES-EQ")
    amount: float = Field(..., gt=0, description="Total capital to deploy")
    threshold: float = Field(5.0, gt=0, le=100, description="Drift threshold percentage")

class AssetStatus(BaseModel):
    ticker: str
    target_weight: float
    current_weight: float
    drift: float
    value: float
    price: float

class PortfolioStatusResponse(BaseModel):
    total_value: float
    pnl_today: float
    rebalance_needed: bool
    threshold: float
    assets: List[AssetStatus]

class TradeAction(BaseModel):
    date: datetime
    action: str
    asset: str
    qty: int
    price: float
    reason: Optional[str] = None
