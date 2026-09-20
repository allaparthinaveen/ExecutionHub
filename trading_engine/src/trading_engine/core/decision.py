from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime
from trading_engine.models.enums import TrailingAction

class TrailingDecision(BaseModel):
    action: TrailingAction
    proposed_stop: Optional[Decimal] = None
    previous_stop: Optional[Decimal] = None
    reason_code: str
    reason_message: str
    trigger_price: Optional[Decimal] = None
    profit: Optional[Decimal] = None
    profit_r: Optional[Decimal] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    policy_name: str
    policy_version: str
    calculation_metadata: Dict[str, Any] = Field(default_factory=dict)
