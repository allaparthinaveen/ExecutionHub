from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
import math

from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide
from trading_engine.core.decision import TrailingDecision

class ValidationError(Exception):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        self.message = message
        super().__init__(self.message)

def normalize_price(price: Decimal, tick_size: Decimal) -> Decimal:
    """Normalize price according to the instrument tick size."""
    if tick_size <= 0:
        return price
    
    # price = round(price / tick_size) * tick_size
    multiplier = price / tick_size
    rounded_multiplier = multiplier.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    
    normalized = rounded_multiplier * tick_size
    
    # Figure out the number of decimal places from tick_size to format nicely
    tick_str = str(tick_size)
    if '.' in tick_str:
        decimal_places = len(tick_str.split('.')[1].rstrip('0'))
        if decimal_places > 0:
            quantize_format = Decimal('10') ** -decimal_places
            return normalized.quantize(quantize_format)
    
    return normalized.quantize(Decimal('1'))

def validate_stop_decision(decision: TrailingDecision, position: Position, market: MarketState) -> None:
    """
    Validate a trailing decision before applying it to the broker.
    Raises ValidationError if any check fails.
    """
    if decision.action.value not in ["MOVE_STOP", "MOVE_TO_BREAKEVEN"]:
        return

    proposed_stop = decision.proposed_stop
    if proposed_stop is None:
        raise ValidationError("MISSING_PROPOSED_STOP", "Decision to move stop missing proposed_stop value.")
        
    # 1. Normalize tick size
    normalized_stop = normalize_price(proposed_stop, market.tick_size)
    
    # 2. Universal Stop Rule: never worsen protection
    if position.current_stop_loss is not None:
        if position.side == OrderSide.BUY:
            if normalized_stop < position.current_stop_loss:
                raise ValidationError(
                    "STOP_REGRESSION_BUY", 
                    f"Proposed stop {normalized_stop} is lower than current stop {position.current_stop_loss} for BUY position."
                )
        elif position.side == OrderSide.SELL:
            if normalized_stop > position.current_stop_loss:
                raise ValidationError(
                    "STOP_REGRESSION_SELL", 
                    f"Proposed stop {normalized_stop} is higher than current stop {position.current_stop_loss} for SELL position."
                )
                
    # 3. Minimum stop distance from current price
    if position.side == OrderSide.BUY:
        distance = market.bid - normalized_stop
        if distance < market.min_stop_distance:
            raise ValidationError(
                "MIN_STOP_DISTANCE_VIOLATION",
                f"Proposed stop {normalized_stop} is too close to market bid {market.bid}. Min distance: {market.min_stop_distance}"
            )
    else:
        distance = normalized_stop - market.ask
        if distance < market.min_stop_distance:
            raise ValidationError(
                "MIN_STOP_DISTANCE_VIOLATION",
                f"Proposed stop {normalized_stop} is too close to market ask {market.ask}. Min distance: {market.min_stop_distance}"
            )
            
    # 4. Correct side check (Stop must be below price for BUY, above for SELL)
    if position.side == OrderSide.BUY and normalized_stop >= market.bid:
        raise ValidationError("INVALID_STOP_SIDE", f"BUY stop {normalized_stop} must be below current bid {market.bid}.")
    if position.side == OrderSide.SELL and normalized_stop <= market.ask:
        raise ValidationError("INVALID_STOP_SIDE", f"SELL stop {normalized_stop} must be above current ask {market.ask}.")
        
    # 5. Timestamp freshness (reject if decision is older than 5 seconds)
    now = datetime.utcnow()
    age = (now - decision.timestamp).total_seconds()
    if age > 5.0:
        raise ValidationError("STALE_DECISION", f"Decision is too old ({age} seconds).")
        
    # Validation passed. Update decision's proposed stop to the normalized one.
    decision.proposed_stop = normalized_stop
