from decimal import Decimal
from datetime import datetime
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class StepTrailingPolicy(TrailingPolicy):
    def __init__(self, activation_distance: Decimal, trailing_distance: Decimal, step_size: Decimal):
        self.activation_distance = activation_distance
        self.trailing_distance = trailing_distance
        self.step_size = step_size
        
    @property
    def name(self) -> str:
        return "step_trailing"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"step_trailing_{self.activation_distance}_{self.trailing_distance}_{self.step_size}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        current_profit = position.current_profit_distance
        
        # Check activation
        if not state.activation_state:
            if current_profit >= self.activation_distance:
                state.activation_state = True
                state.activation_timestamp = datetime.utcnow().isoformat()
            else:
                return TrailingDecision(
                    action=TrailingAction.NO_ACTION,
                    reason_code="ACTIVATION_NOT_REACHED",
                    reason_message=f"Current profit {current_profit} < {self.activation_distance}",
                    policy_name=self.name,
                    policy_version=self.version
                )
                
        # Calculate theoretical continuous stop
        if position.side == OrderSide.BUY:
            ref_price = state.highest_price or market.last
            theoretical_stop = ref_price - self.trailing_distance
            
            if position.current_stop_loss is None or (theoretical_stop - position.current_stop_loss) >= self.step_size:
                proposed_stop = theoretical_stop
            else:
                return TrailingDecision(
                    action=TrailingAction.NO_ACTION,
                    reason_code="STEP_NOT_REACHED",
                    reason_message=f"Improvement < {self.step_size}",
                    policy_name=self.name,
                    policy_version=self.version
                )
        else:
            ref_price = state.lowest_price or market.last
            theoretical_stop = ref_price + self.trailing_distance
            
            if position.current_stop_loss is None or (position.current_stop_loss - theoretical_stop) >= self.step_size:
                proposed_stop = theoretical_stop
            else:
                return TrailingDecision(
                    action=TrailingAction.NO_ACTION,
                    reason_code="STEP_NOT_REACHED",
                    reason_message=f"Improvement < {self.step_size}",
                    policy_name=self.name,
                    policy_version=self.version
                )
                
        return TrailingDecision(
            action=TrailingAction.MOVE_STOP,
            proposed_stop=proposed_stop,
            previous_stop=position.current_stop_loss,
            reason_code="STEP_REACHED",
            reason_message=f"Step of {self.step_size} reached, moving stop.",
            profit_r=position.profit_r,
            policy_name=self.name,
            policy_version=self.version
        )
