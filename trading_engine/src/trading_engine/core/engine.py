import structlog
from datetime import datetime, timezone
import hashlib

from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction
from trading_engine.policies.base import TrailingPolicy, TrailingState
from trading_engine.brokers.base import BrokerAdapter
from trading_engine.persistence.state_store import StateStore
from trading_engine.core.validation import validate_stop_decision, ValidationError

logger = structlog.get_logger("trailing_engine")

class TrailingEngine:
    def __init__(self, broker: BrokerAdapter, store: StateStore, policy: TrailingPolicy):
        self.broker = broker
        self.store = store
        self.policy = policy
        
    def _generate_idempotency_key(self, position_id: str, proposed_stop: str, state_version: str) -> str:
        raw_key = f"{position_id}_{proposed_stop}_{self.policy.version}_{state_version}"
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    def process_tick(self, position_id: str, market: MarketState) -> None:
        """Process a market tick for a given position."""
        
        # 1. Load Position and State
        position = self.store.get_position(position_id)
        if not position:
            logger.warning("POSITION_NOT_FOUND", position_id=position_id)
            return
            
        state = self.store.get_trailing_state(position_id)
        if not state:
            state = TrailingState(position_id)
            
        # Update state tracking variables (highest/lowest prices)
        if state.highest_price is None or market.last > state.highest_price:
            state.highest_price = market.last
            position.highest_price_since_entry = market.last
            
        if state.lowest_price is None or market.last < state.lowest_price:
            state.lowest_price = market.last
            position.lowest_price_since_entry = market.last
            
        position.current_price = market.last

        # 2. Evaluate Policy
        decision = self.policy.evaluate(position, market, state)
        
        if decision.action in [TrailingAction.NO_ACTION, TrailingAction.REJECT, TrailingAction.ERROR]:
            if decision.action != TrailingAction.NO_ACTION:
                logger.debug("TRAILING_DECISION", 
                             action=decision.action.value, 
                             reason=decision.reason_code, 
                             position_id=position_id)
            self.store.save_position(position)
            self.store.save_trailing_state(state)
            return
            
        # 3. Validation
        try:
            validate_stop_decision(decision, position, market)
        except ValidationError as e:
            logger.warning("STOP_REJECTED", 
                           position_id=position_id,
                           reason=e.reason_code,
                           message=e.message,
                           proposed_stop=str(decision.proposed_stop))
            # Save the updated high/lows anyway
            self.store.save_position(position)
            self.store.save_trailing_state(state)
            return

        # 4. Idempotency & Broker Execution
        if decision.action in [TrailingAction.MOVE_STOP, TrailingAction.MOVE_TO_BREAKEVEN]:
            if decision.proposed_stop == position.current_stop_loss:
                # No actual movement needed
                return
                
            state_version = state.last_stop_update_timestamp or str(datetime.utcnow().timestamp())
            idem_key = self._generate_idempotency_key(position_id, str(decision.proposed_stop), state_version)
            
            logger.info("STOP_MOVE_REQUESTED", 
                        position_id=position_id,
                        symbol=position.symbol,
                        side=position.side.value,
                        old_stop=str(position.current_stop_loss),
                        new_stop=str(decision.proposed_stop),
                        price=str(market.last),
                        profit_r=str(decision.profit_r) if decision.profit_r else None,
                        reason=decision.reason_code)
                        
            success = self.broker.modify_stop(position_id, decision.proposed_stop, idem_key)
            
            if success:
                logger.info("STOP_MOVE_ACCEPTED", position_id=position_id)
                position.current_stop_loss = decision.proposed_stop
                state.current_stop = decision.proposed_stop
                state.last_stop_update = decision.proposed_stop
                state.last_stop_update_timestamp = datetime.utcnow().isoformat()
            else:
                logger.error("STOP_MOVE_FAILED", position_id=position_id)
                
        # 5. Save State
        self.store.save_position(position)
        self.store.save_trailing_state(state)
