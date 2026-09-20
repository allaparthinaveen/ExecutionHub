from decimal import Decimal
from datetime import datetime
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction, OrderSide
from trading_engine.core.decision import TrailingDecision

class SamuraiTrailingPolicy(TrailingPolicy):
    """
    The frozen, reverse-engineered trailing policy for Samurai AI.
    Based on forensic analysis of statement.csv, this implements a 
    hybrid Break-even + Step Trailing approach.
    """
    def __init__(self, activation_pts: Decimal, step_pts: Decimal):
        self.activation_pts = activation_pts
        self.step_pts = step_pts
        
    @property
    def name(self) -> str:
        return "samurai_trailing_og"
        
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def configuration_hash(self) -> str:
        return f"samurai_{self.activation_pts}_{self.step_pts}"
        
    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        current_profit_pts = position.current_profit_distance
        
        # Check Break-even Activation
        if not state.activation_state:
            if current_profit_pts >= self.activation_pts:
                state.activation_state = True
                state.activation_timestamp = datetime.utcnow().isoformat()
                
                # Move to breakeven + 1 tick buffer
                buffer = market.tick_size
                proposed = position.entry_price + buffer if position.side == OrderSide.BUY else position.entry_price - buffer
                
                return TrailingDecision(
                    action=TrailingAction.MOVE_TO_BREAKEVEN,
                    proposed_stop=proposed,
                    previous_stop=position.current_stop_loss,
                    reason_code="SAMURAI_ACTIVATED",
                    reason_message=f"Profit {current_profit_pts} >= {self.activation_pts}, moving to BE",
                    policy_name=self.name,
                    policy_version=self.version
                )
            else:
                return TrailingDecision(
                    action=TrailingAction.NO_ACTION,
                    reason_code="WAITING",
                    reason_message="Waiting for activation",
                    policy_name=self.name,
                    policy_version=self.version
                )
                
        # Once activated, apply Step Trailing
        steps = int((current_profit_pts - self.activation_pts) / self.step_pts)
        if steps > 0:
            distance_to_lock = steps * self.step_pts
            
            if position.side == OrderSide.BUY:
                proposed_stop = position.entry_price + distance_to_lock
                is_improvement = position.current_stop_loss is None or proposed_stop > position.current_stop_loss
            else:
                proposed_stop = position.entry_price - distance_to_lock
                is_improvement = position.current_stop_loss is None or proposed_stop < position.current_stop_loss
                
            if is_improvement:
                return TrailingDecision(
                    action=TrailingAction.MOVE_STOP,
                    proposed_stop=proposed_stop,
                    previous_stop=position.current_stop_loss,
                    reason_code="SAMURAI_STEP",
                    reason_message=f"Locked in {steps} steps of profit",
                    policy_name=self.name,
                    policy_version=self.version
                )
                
        return TrailingDecision(
            action=TrailingAction.NO_ACTION,
            reason_code="MAINTAINING",
            reason_message="Step distance not reached",
            policy_name=self.name,
            policy_version=self.version
        )
