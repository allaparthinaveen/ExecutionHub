from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional
from datetime import datetime

class MarketState(BaseModel):
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    spread: Decimal
    timestamp: datetime
    tick_size: Decimal
    point_size: Decimal
    min_stop_distance: Decimal
    volatility: Optional[Decimal] = None
    atr_values: Optional[dict[str, Decimal]] = None
    session: Optional[str] = None
    market_status: str = "OPEN"
