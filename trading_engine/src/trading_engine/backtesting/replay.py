from decimal import Decimal
import structlog
from typing import List, Dict

from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.policies.base import TrailingPolicy, TrailingState

logger = structlog.get_logger("trading_engine.backtesting.replay")

class ReplayEngine:
    """
    Event-driven backtesting engine to replay historical market ticks 
    against a specific TrailingPolicy to see if it matches observed broker statements.
    """
    def __init__(self, policy: TrailingPolicy):
        self.policy = policy
        self.positions: Dict[str, Position] = {}
        self.states: Dict[str, TrailingState] = {}
        self.events = []
        
    def add_position(self, position: Position):
        self.positions[position.position_id] = position
        self.states[position.position_id] = TrailingState(position.position_id)
        
    def process_tick(self, market: MarketState):
        for pos_id, position in self.positions.items():
            if position.status != "OPEN":
                continue
                
            state = self.states[pos_id]
            
            # Update high/low tracking
            if state.highest_price is None or market.last > state.highest_price:
                state.highest_price = market.last
                position.highest_price_since_entry = market.last
                
            if state.lowest_price is None or market.last < state.lowest_price:
                state.lowest_price = market.last
                position.lowest_price_since_entry = market.last
                
            position.current_price = market.last
            
            decision = self.policy.evaluate(position, market, state)
            
            if decision.action.value in ["MOVE_STOP", "MOVE_TO_BREAKEVEN"]:
                if decision.proposed_stop != position.current_stop_loss:
                    self.events.append({
                        "timestamp": market.timestamp,
                        "position_id": pos_id,
                        "action": decision.action.value,
                        "old_stop": position.current_stop_loss,
                        "new_stop": decision.proposed_stop,
                        "price": market.last
                    })
                    position.current_stop_loss = decision.proposed_stop
                    state.current_stop = decision.proposed_stop
                    
    def get_events(self) -> List[Dict]:
        return self.events
