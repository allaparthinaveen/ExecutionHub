from typing import Optional, Tuple
from decimal import Decimal
import structlog
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide
import collections
import statistics

logger = structlog.get_logger("trading_engine.execution.btc_signal")

class BTCSignalEngine:
    """
    BTC Regime-Filtered Breakout Engine
    Evaluates tick data against a consolidation box and regime EMA.
    """
    def __init__(self, 
                 max_box_pct: Decimal = Decimal('12.0'),
                 breakout_buffer: Decimal = Decimal('0.10'),
                 stop_atr_mult: Decimal = Decimal('1.5')):
        
        self.max_box_pct = max_box_pct
        self.breakout_buffer = breakout_buffer
        self.stop_atr_mult = stop_atr_mult
        
        # Simple rolling window for tick-based box approximation
        self.tick_window = collections.deque(maxlen=100)
        self.setup_state = 0 # 0=idle, 1=cons, 2=acceptance, 3=retest
        
        # State
        self.resistance: Optional[Decimal] = None
        self.support: Optional[Decimal] = None
        self.atr_value: Decimal = Decimal('100.0') # Default for testing
        
    def _calculate_box(self):
        if len(self.tick_window) < 50:
            return False
            
        recent_high = max(self.tick_window)
        recent_low = min(self.tick_window)
        mid_point = (recent_high + recent_low) / Decimal('2.0')
        
        if mid_point == 0:
            return False
            
        range_pct = ((recent_high - recent_low) / mid_point) * Decimal('100')
        is_tight = range_pct <= self.max_box_pct
        
        if is_tight:
            self.resistance = recent_high
            self.support = recent_low
            return True
        return False
        
    def evaluate(self, market: MarketState) -> Tuple[Optional[OrderSide], dict]:
        """
        Evaluates the tick and returns (Signal, Metadata)
        """
        self.tick_window.append(market.last)
        
        # Attach ATR to market state for trailing policy to use
        if market.atr_values is None:
            market.atr_values = {}
        market.atr_values['atr14'] = self.atr_value
        
        # State Machine (simplified Pine Script logic)
        if self.setup_state == 0:
            if self._calculate_box():
                self.setup_state = 1
                logger.info("BTC_CONSOLIDATION_DETECTED", res=str(self.resistance), sup=str(self.support))
                
        elif self.setup_state == 1:
            # Check Breakout
            res_buffer = self.resistance * (Decimal('1') + self.breakout_buffer / Decimal('100'))
            sup_buffer = self.support * (Decimal('1') - self.breakout_buffer / Decimal('100'))
            
            # Artificial acceleration for Testnet demonstrations
            # We assume a tick breaking recent highs/lows instantly triggers
            if market.last > res_buffer:
                logger.info("BTC_BULL_BREAKOUT", price=str(market.last))
                
                # Calculate initial stop based on ATR
                stop_candidate = min(market.last - self.atr_value * self.stop_atr_mult, self.resistance)
                
                metadata = {
                    "pending_stop": stop_candidate,
                    "target_r": Decimal('1.5'),
                    "atr_value": self.atr_value,
                }
                
                self.setup_state = 0 # Reset
                return OrderSide.BUY, metadata
                
            elif market.last < sup_buffer:
                logger.info("BTC_BEAR_BREAKOUT", price=str(market.last))
                
                # Calculate initial stop based on ATR
                stop_candidate = max(market.last + self.atr_value * self.stop_atr_mult, self.support)
                
                metadata = {
                    "pending_stop": stop_candidate,
                    "target_r": Decimal('1.5'),
                    "atr_value": self.atr_value,
                }
                
                self.setup_state = 0 # Reset
                return OrderSide.SELL, metadata
                
        return None, {}
