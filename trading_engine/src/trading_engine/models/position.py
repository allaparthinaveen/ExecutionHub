from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime

from .enums import OrderSide, PositionStatus

class Position(BaseModel):
    position_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    
    initial_stop_loss: Optional[Decimal] = None
    current_stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    
    activation_price: Optional[Decimal] = None
    highest_price_since_entry: Decimal
    lowest_price_since_entry: Decimal
    
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    
    opened_at: datetime
    updated_at: datetime
    
    broker: str
    account_id_hash: str
    status: PositionStatus = PositionStatus.OPEN
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @property
    def initial_risk(self) -> Optional[Decimal]:
        if self.initial_stop_loss is None:
            return None
        return abs(self.entry_price - self.initial_stop_loss)

    @property
    def current_profit_distance(self) -> Decimal:
        if self.side == OrderSide.BUY:
            return self.current_price - self.entry_price
        else:
            return self.entry_price - self.current_price

    @property
    def profit_r(self) -> Optional[Decimal]:
        risk = self.initial_risk
        if not risk:
            return None
        return self.current_profit_distance / risk
