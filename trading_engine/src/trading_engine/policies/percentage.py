from decimal import Decimal
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class PercentagePolicy(TrailingPolicy):
    def __init__(self, percentage: Decimal):
        """percentage should be a decimal like 0.02 for 2%"""
        self.percentage = percentage
        
    @property
    def name(self) -> str:
        return "percentage"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"percentage_{self.percentage}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        if position.side == OrderSide.BUY:
            ref_price = state.highest_price or market.last
            proposed_stop = ref_price * (Decimal('1') - self.percentage)
        else:
            ref_price = state.lowest_price or market.last
            proposed_stop = ref_price * (Decimal('1') + self.percentage)
            
        return TrailingDecision(
            action=TrailingAction.MOVE_STOP,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="PERCENTAGE",
            reason_message=f"Maintained {self.percentage*100}% distance",
            profit_r=position.profit_r,
            policy_name=self.name,
            policy_version=self.version
        )
