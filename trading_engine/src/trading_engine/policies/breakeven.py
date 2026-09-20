from decimal import Decimal
from datetime import datetime
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class BreakevenPolicy(TrailingPolicy):
    def __init__(self, activation_r: Decimal, buffer: Decimal = Decimal('0')):
        self.activation_r = activation_r
        self.buffer = buffer
        
    @property
    def name(self) -> str:
        return "breakeven"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"breakeven_{self.activation_r}_{self.buffer}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        if state.activation_state:
            return TrailingDecision(
                action=TrailingAction.NO_ACTION,
                reason_code="ALREADY_ACTIVATED",
                reason_message="Breakeven was already applied.",
                policy_name=self.name,
                policy_version=self.version
            )
            
        current_r = position.profit_r
        if current_r is None or current_r < self.activation_r:
            return TrailingDecision(
                action=TrailingAction.NO_ACTION,
                reason_code="ACTIVATION_NOT_REACHED",
                reason_message=f"Current R {current_r} is below activation R {self.activation_r}",
                policy_name=self.name,
                policy_version=self.version
            )
            
        # Activate and calculate breakeven stop
        state.activation_state = True
        state.activation_timestamp = datetime.utcnow().isoformat()
        
        if position.side == OrderSide.BUY:
            proposed_stop = position.entry_price + self.buffer
        else:
            proposed_stop = position.entry_price - self.buffer
            
        return TrailingDecision(
            action=TrailingAction.MOVE_TO_BREAKEVEN,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="BREAKEVEN_ACTIVATED",
            reason_message=f"Price reached {self.activation_r}R, moving to breakeven + buffer {self.buffer}",
            profit_r=current_r,
            policy_name=self.name,
            policy_version=self.version
        )
