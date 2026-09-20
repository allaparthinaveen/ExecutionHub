from typing import Optional
from decimal import Decimal
import structlog
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide
from datetime import datetime

logger = structlog.get_logger("trading_engine.execution.signal")

class SamuraiSignalEngine:
    """
    Evaluates the live MarketState tick-by-tick against the Samurai Core Algorithm
    (Daily Straddle Breakout) to emit Entry Signals.
    """
    def __init__(self):
        # In a full implementation, this would fetch the previous daily H/L from the broker
        # using the 1h server-day rollup logic.
        # For testnet demonstration, we set arbitrary breakout thresholds around the current price.
        self.daily_high_cache: Optional[Decimal] = None
        self.daily_low_cache: Optional[Decimal] = None
        self.straddle_armed = False
        
    def evaluate(self, market: MarketState) -> Optional[OrderSide]:
        # Initialize levels if not set
        if self.daily_high_cache is None or self.daily_low_cache is None:
            # We simulate the previous day's range being a tight band around current price
            # so that it breaks out quickly for testing purposes on the testnet.
            self.daily_high_cache = market.last + Decimal('2.0')
            self.daily_low_cache = market.last - Decimal('2.0')
            self.straddle_armed = True
            logger.info("STRADDLE_ARMED", high=str(self.daily_high_cache), low=str(self.daily_low_cache))
            
        if not self.straddle_armed:
            return None
            
        # Check Breakout Condition (Samurai Core Entry Logic)
        if market.last >= self.daily_high_cache:
            logger.info("BREAKOUT_DETECTED", condition="PRICE_ABOVE_HIGH", price=str(market.last))
            self.straddle_armed = False # Disarm until next day
            return OrderSide.BUY
            
        if market.last <= self.daily_low_cache:
            logger.info("BREAKOUT_DETECTED", condition="PRICE_BELOW_LOW", price=str(market.last))
            self.straddle_armed = False # Disarm until next day
            return OrderSide.SELL
            
        return None
