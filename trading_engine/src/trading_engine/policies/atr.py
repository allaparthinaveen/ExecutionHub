from decimal import Decimal
from datetime import datetime
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class ATRTrailingPolicy(TrailingPolicy):
    def __init__(self, atr_multiplier: Decimal, activation_r: Decimal = Decimal('0')):
        self.atr_multiplier = atr_multiplier
        self.activation_r = activation_r
        
    @property
    def name(self) -> str:
        return "atr_trailing"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"atr_trailing_{self.atr_multiplier}_{self.activation_r}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        current_r = position.profit_r
        
        # Check activation
        if not state.activation_state:
            if current_r is not None and current_r >= self.activation_r:
                state.activation_state = True
                state.activation_timestamp = datetime.utcnow().isoformat()
            else:
                return TrailingDecision(
                    action=TrailingAction.NO_ACTION,
                    reason_code="ACTIVATION_NOT_REACHED",
                    reason_message=f"Current R {current_r} < {self.activation_r}",
                    policy_name=self.name,
                    policy_version=self.version
                )

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
        
        if position.side == OrderSide.BUY:
            ref_price = state.highest_price or market.last
            proposed_stop = ref_price - distance
        else:
            ref_price = state.lowest_price or market.last
            proposed_stop = ref_price + distance
            
        return TrailingDecision(
            action=TrailingAction.MOVE_STOP,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="ATR_TRAIL",
            reason_message=f"Trailing by {self.atr_multiplier}x ATR ({atr_value})",
            profit_r=current_r,
            policy_name=self.name,
            policy_version=self.version
        )
