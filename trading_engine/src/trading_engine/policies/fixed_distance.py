from decimal import Decimal
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class FixedDistancePolicy(TrailingPolicy):
    def __init__(self, distance: Decimal):
        self.distance = distance
        
    @property
    def name(self) -> str:
        return "fixed_distance"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"fixed_distance_{self.distance}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        current_price = market.last
        
        if position.side == OrderSide.BUY:
            proposed_stop = state.highest_price - self.distance if state.highest_price else current_price - self.distance
        else:
            proposed_stop = state.lowest_price + self.distance if state.lowest_price else current_price + self.distance
            
        return TrailingDecision(
            action=TrailingAction.MOVE_STOP,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="FIXED_DISTANCE",
            reason_message=f"Maintained fixed distance of {self.distance}",
            profit_r=position.profit_r,
            policy_name=self.name,
            policy_version=self.version
        )
