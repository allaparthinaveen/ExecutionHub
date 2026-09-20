from decimal import Decimal
from datetime import datetime
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class ChandelierExitPolicy(TrailingPolicy):
    def __init__(self, atr_multiplier: Decimal):
        """Standard chandelier uses a multiplier of ATR subtracted from highest high."""
        self.atr_multiplier = atr_multiplier
        
    @property
    def name(self) -> str:
        return "chandelier_exit"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"chandelier_exit_{self.atr_multiplier}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        if not market.atr_values or "ATR" not in market.atr_values:
            return TrailingDecision(
                action=TrailingAction.NO_ACTION,
                reason_code="MISSING_ATR_DATA",
                reason_message="ATR values not present in MarketState",
                policy_name=self.name,
                policy_version=self.version
            )
            
        atr_value = market.atr_values["ATR"]
        distance = atr_value * self.atr_multiplier
        
        # Chandelier specifically uses highest high or lowest low since entry
        if position.side == OrderSide.BUY:
            ref_price = position.highest_price_since_entry
            proposed_stop = ref_price - distance
        else:
            ref_price = position.lowest_price_since_entry
            proposed_stop = ref_price + distance
            
        return TrailingDecision(
            action=TrailingAction.MOVE_STOP,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="CHANDELIER_UPDATE",
            reason_message=f"Chandelier Exit using {self.atr_multiplier}x ATR",
            profit_r=position.profit_r,
            policy_name=self.name,
            policy_version=self.version
        )
