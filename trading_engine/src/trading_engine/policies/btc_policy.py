from decimal import Decimal
import structlog
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import TrailingAction
from trading_engine.policies.base import TrailingPolicy, TrailingState, TrailingDecision
from typing import Optional

logger = structlog.get_logger("trading_engine.policies.btc")

class BTCRegimeTrailingPolicy(TrailingPolicy):
    """
    Implements the tick-based dynamic exit strategy from the BTC Regime-Filtered Breakout.
    """
    name = "btc_regime_breakout"
    version = "1.0.0"
    
    def __init__(self, target_r: Decimal = Decimal('1.5'),
                 move_be_at_r: Decimal = Decimal('1.0'),
                 trail_start_r: Decimal = Decimal('1.0'),
                 trail_atr_mult: Decimal = Decimal('1.0'),
                 stop_atr_mult: Decimal = Decimal('1.5')):
        self.target_r = target_r
        self.move_be_at_r = move_be_at_r
        self.trail_start_r = trail_start_r
        self.trail_atr_mult = trail_atr_mult
        self.stop_atr_mult = stop_atr_mult

    def evaluate(self, position: Position, market: MarketState, state: TrailingState) -> TrailingDecision:
        # First tick initialization
        if position.initial_stop_loss is None:
            atr = market.atr_values.get('atr14', Decimal('100.0')) if market.atr_values else Decimal('100.0')
            
            if position.side.value == "BUY":
                position.initial_stop_loss = position.entry_price - atr * self.stop_atr_mult
            else:
                position.initial_stop_loss = position.entry_price + atr * self.stop_atr_mult
                
            position.current_stop_loss = position.initial_stop_loss
            state.current_stop = position.initial_stop_loss
            
            # Calculate Target
            risk = position.initial_risk
            if position.side.value == "BUY":
                position.take_profit = position.entry_price + (risk * self.target_r)
            else:
                position.take_profit = position.entry_price - (risk * self.target_r)
                
            return TrailingDecision(
                action=TrailingAction.MOVE_STOP,
                proposed_stop=position.initial_stop_loss,
                previous_stop=None,
                reason_code="INITIAL_STOP_SET",
                reason_message="Initial stop calculated from ATR",
                profit_r=Decimal('0')
            )
            
        r_mult = position.profit_r or Decimal('0')
        atr = market.atr_values.get('atr14', Decimal('100.0')) if market.atr_values else Decimal('100.0')
        
        # 1. Target Hit check
        if position.take_profit:
            if position.side.value == "BUY" and market.last >= position.take_profit:
                return TrailingDecision(action=TrailingAction.CLOSE_POSITION, proposed_stop=position.current_stop_loss, previous_stop=position.current_stop_loss, reason_code="TARGET_HIT", profit_r=r_mult)
            elif position.side.value == "SELL" and market.last <= position.take_profit:
                return TrailingDecision(action=TrailingAction.CLOSE_POSITION, proposed_stop=position.current_stop_loss, previous_stop=position.current_stop_loss, reason_code="TARGET_HIT", profit_r=r_mult)

        # 2. Stop Exit check
        if position.side.value == "BUY" and market.last <= position.current_stop_loss:
            return TrailingDecision(action=TrailingAction.CLOSE_POSITION, proposed_stop=position.current_stop_loss, previous_stop=position.current_stop_loss, reason_code="STOP_HIT", profit_r=r_mult)
        if position.side.value == "SELL" and market.last >= position.current_stop_loss:
            return TrailingDecision(action=TrailingAction.CLOSE_POSITION, proposed_stop=position.current_stop_loss, previous_stop=position.current_stop_loss, reason_code="STOP_HIT", profit_r=r_mult)

        proposed_stop = position.current_stop_loss
        reason = "NO_ACTION"

        # 3. Move to BE
        be_moved = state.metadata.get("be_moved", False)
        if not be_moved and r_mult > Decimal('0'):
            if position.side.value == "BUY" and market.last >= position.entry_price + position.initial_risk * self.move_be_at_r:
                proposed_stop = max(proposed_stop, position.entry_price)
                state.metadata["be_moved"] = True
                reason = "MOVE_TO_BE"
            elif position.side.value == "SELL" and market.last <= position.entry_price - position.initial_risk * self.move_be_at_r:
                proposed_stop = min(proposed_stop, position.entry_price)
                state.metadata["be_moved"] = True
                reason = "MOVE_TO_BE"

        # 4. Trailing
        if r_mult > Decimal('0'):
            if position.side.value == "BUY" and market.last >= position.entry_price + position.initial_risk * self.trail_start_r:
                new_stop = market.last - atr * self.trail_atr_mult
                if new_stop > proposed_stop:
                    proposed_stop = new_stop
                    reason = "TRAILING_UPDATE"
            elif position.side.value == "SELL" and market.last <= position.entry_price - position.initial_risk * self.trail_start_r:
                new_stop = market.last + atr * self.trail_atr_mult
                if new_stop < proposed_stop:
                    proposed_stop = new_stop
                    reason = "TRAILING_UPDATE"

        if proposed_stop != position.current_stop_loss:
            return TrailingDecision(
                action=TrailingAction.MOVE_STOP,
                proposed_stop=proposed_stop,
                previous_stop=position.current_stop_loss,
                reason_code=reason,
                profit_r=r_mult
            )
            
        return TrailingDecision(action=TrailingAction.NO_ACTION, proposed_stop=position.current_stop_loss, previous_stop=position.current_stop_loss, reason_code="NO_ACTION", profit_r=r_mult)
