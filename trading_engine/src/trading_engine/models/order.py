from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime

from .enums import OrderSide, OrderType

class Order(BaseModel):
    order_id: str
    position_id: Optional[str] = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    
    created_at: datetime
    updated_at: datetime
    
    broker: str
    status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
