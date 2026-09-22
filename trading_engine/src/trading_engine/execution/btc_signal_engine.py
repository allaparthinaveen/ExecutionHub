from typing import Optional, Tuple, List
from decimal import Decimal
import structlog
from datetime import datetime
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide
import collections

logger = structlog.get_logger("trading_engine.execution.btc_signal")

class Kline:
    def __init__(self, timestamp: datetime, open_p: Decimal, high: Decimal, low: Decimal, close: Decimal):
        self.timestamp = timestamp
        self.open = open_p
        self.high = high
        self.low = low
        self.close = close

class BTCSignalEngine:
    """
    BTC Regime-Filtered Breakout Engine
    Faithful translation of Pine Script Logic (1h timeframe aggregation).
    """
    def __init__(self, 
                 pivot_len: int = 3,
                 min_trend_swings: int = 2,
                 min_cons_bars: int = 8,
                 max_cons_bars: int = 50,
                 max_box_pct: Decimal = Decimal('12.0'),
                 contraction_ratio: Decimal = Decimal('1.10'),
                 breakout_buffer: Decimal = Decimal('0.10'),
                 use_regime: bool = True,
                 regime_ema_len: int = 50,
                 accept_bars: int = 1,
                 retest_bars: int = 25,
                 retest_buffer: Decimal = Decimal('0.75'),
                 atr_len: int = 14,
                 stop_atr_mult: Decimal = Decimal('2.0'),
                 min_stop_pct: Decimal = Decimal('0.003'),
                 target_r: Decimal = Decimal('2.0'),
                 allow_shorts: bool = True):
        
        self.pivot_len = pivot_len
        self.min_trend_swings = min_trend_swings
        self.min_cons_bars = min_cons_bars
        self.max_cons_bars = max_cons_bars
        self.max_box_pct = max_box_pct
        self.contraction_ratio = contraction_ratio
        self.breakout_buffer = breakout_buffer
        self.use_regime = use_regime
        self.regime_ema_len = regime_ema_len
        self.accept_bars = accept_bars
        self.retest_bars = retest_bars
        self.retest_buffer = retest_buffer
        self.atr_len = atr_len
        self.stop_atr_mult = stop_atr_mult
        self.min_stop_pct = min_stop_pct
        self.target_r = target_r
        self.allow_shorts = allow_shorts
        
        # State variables
        self.klines: List[Kline] = []
        self.current_kline: Optional[Kline] = None
        
        # Indicators
        self.ema: Optional[Decimal] = None
        self.atr: Optional[Decimal] = None
        
        self.ph_queue = collections.deque(maxlen=self.pivot_len * 2 + 1)
        self.pl_queue = collections.deque(maxlen=self.pivot_len * 2 + 1)
        
        self.prev_high: Optional[Decimal] = None
        self.last_high: Optional[Decimal] = None
        self.prev_low: Optional[Decimal] = None
        self.last_low: Optional[Decimal] = None
        
        self.hh_count = 0
        self.hl_count = 0
        self.lh_count = 0
        self.ll_count = 0
        self.trend = 0
        self.prev_trend = 0
        
        self.setup_state = 0   # 0=idle, 1=cons, 2=acceptance, 3=retest
        self.cycle_used = False
        self.resistance: Optional[Decimal] = None
        self.support: Optional[Decimal] = None
        self.box_high1: Optional[Decimal] = None
        self.box_low1: Optional[Decimal] = None
        self.accept_ct = 0
        self.rt_start_bar: Optional[int] = None
        self.bo_bar: Optional[int] = None

    def _truncate_hour(self, dt: datetime) -> datetime:
        return dt.replace(minute=0, second=0, microsecond=0)

    def _update_indicators(self):
        if not self.klines:
            return
            
        k = self.klines[-1]
        
        # EMA (TradingView standard EMA)
        if self.ema is None:
            if len(self.klines) >= self.regime_ema_len:
                # Simple SMA for first EMA value
                sm = sum(x.close for x in self.klines[-self.regime_ema_len:]) / Decimal(self.regime_ema_len)
                self.ema = sm
        else:
            alpha = Decimal('2.0') / Decimal(self.regime_ema_len + 1)
            self.ema = (k.close * alpha) + (self.ema * (Decimal('1') - alpha))
            
        # ATR (TradingView RMA)
        if len(self.klines) > 1:
            prev_k = self.klines[-2]
            tr = max(k.high - k.low, abs(k.high - prev_k.close), abs(k.low - prev_k.close))
            if self.atr is None:
                if len(self.klines) >= self.atr_len:
                    # Initial SMA of TR
                    tr_sum = Decimal('0')
                    for i in range(-self.atr_len, 0):
                        pk = self.klines[i-1] if (i-1) >= -len(self.klines) else self.klines[i]
                        r = max(self.klines[i].high - self.klines[i].low, abs(self.klines[i].high - pk.close), abs(self.klines[i].low - pk.close))
                        tr_sum += r
                    self.atr = tr_sum / Decimal(self.atr_len)
            else:
                self.atr = (self.atr * Decimal(self.atr_len - 1) + tr) / Decimal(self.atr_len)
                
        # Pivots
        self.ph_queue.append(k.high)
        self.pl_queue.append(k.low)
        
        new_hh = False
        new_lh = False
        new_hl = False
        new_ll = False
        
        if len(self.ph_queue) == self.ph_queue.maxlen:
            center_h = self.ph_queue[self.pivot_len]
            if all(center_h > self.ph_queue[i] for i in range(len(self.ph_queue)) if i != self.pivot_len):
                ph = center_h
                self.prev_high = self.last_high
                self.last_high = ph
                if self.prev_high is not None:
                    if self.last_high > self.prev_high:
                        new_hh = True
                    elif self.last_high < self.prev_high:
                        new_lh = True
                        
        if len(self.pl_queue) == self.pl_queue.maxlen:
            center_l = self.pl_queue[self.pivot_len]
            if all(center_l < self.pl_queue[i] for i in range(len(self.pl_queue)) if i != self.pivot_len):
                pl = center_l
                self.prev_low = self.last_low
                self.last_low = pl
                if self.prev_low is not None:
                    if self.last_low > self.prev_low:
                        new_hl = True
                    elif self.last_low < self.prev_low:
                        new_ll = True
                        
        if new_hh:
            self.hh_count += 1
            self.lh_count = 0
        if new_hl:
            self.hl_count += 1
        if new_lh:
            self.lh_count += 1
            self.hh_count = 0
        if new_ll:
            self.ll_count += 1
            
        if self.hh_count >= self.min_trend_swings and self.hl_count >= self.min_trend_swings:
            self.trend = 1
        if self.lh_count >= self.min_trend_swings and self.ll_count >= self.min_trend_swings:
            self.trend = -1
            
        trend_changed = (self.trend != 0 and self.trend != self.prev_trend)
        if trend_changed and self.cycle_used:
            self.setup_state = 0
            self.resistance = None
            self.support = None
            self.accept_ct = 0
        if trend_changed:
            self.cycle_used = False
            
        self.prev_trend = self.trend
        
        # Box Detection (on closed bars)
        if len(self.klines) >= self.min_cons_bars:
            recent_high = max(x.high for x in self.klines[-self.min_cons_bars:])
            recent_low = min(x.low for x in self.klines[-self.min_cons_bars:])
            mid_point = (recent_high + recent_low) / Decimal('2.0')
            range_pct = ((recent_high - recent_low) / mid_point) * Decimal('100') if mid_point != 0 else Decimal('999')
            is_tight = range_pct <= self.max_box_pct
            
            if self.trend != 0 and self.setup_state == 0 and not self.cycle_used and is_tight:
                regime_ok = not self.use_regime or (self.ema is not None and ((self.trend == 1 and k.close > self.ema) or (self.trend == -1 and k.close < self.ema)))
                if regime_ok:
                    self.setup_state = 1
                    self.cycle_used = True
                    self.resistance = recent_high
                    self.support = recent_low
                    half = max(1, self.min_cons_bars // 2)
                    self.box_high1 = max(x.high for x in self.klines[-(self.min_cons_bars):-(self.min_cons_bars)+half])
                    self.box_low1 = min(x.low for x in self.klines[-(self.min_cons_bars):-(self.min_cons_bars)+half])
                    logger.info("BOX_DETECTED", res=str(self.resistance), sup=str(self.support), trend=self.trend)

    def evaluate(self, market: MarketState) -> Tuple[Optional[OrderSide], dict]:
        tick_time = self._truncate_hour(market.timestamp)
        
        # 1. Update/Close Klines
        if self.current_kline is None:
            self.current_kline = Kline(tick_time, market.last, market.last, market.last, market.last)
        elif self.current_kline.timestamp != tick_time:
            # Close previous bar
            self.klines.append(self.current_kline)
            # Trim history to save memory
            if len(self.klines) > 200:
                self.klines = self.klines[-200:]
            self._update_indicators()
            # Start new bar
            self.current_kline = Kline(tick_time, market.last, market.last, market.last, market.last)
        else:
            # Update current bar
            self.current_kline.high = max(self.current_kline.high, market.last)
            self.current_kline.low = min(self.current_kline.low, market.last)
            self.current_kline.close = market.last

        # Provide ATR to TrailingPolicy via MarketState
        if market.atr_values is None:
            market.atr_values = {}
        if self.atr is not None:
            market.atr_values['atr14'] = self.atr

        # Ensure we have enough data
        if self.atr is None or len(self.klines) < self.min_cons_bars:
            return None, {}

        # 2. Tick-Based Breakout / Acceptance / Retest Logic
        tick_close = market.last
        tick_high = market.last # Simplifying tick high/low to last price for event driven instantaneous check
        tick_low = market.last
        tick_open = self.current_kline.open
        bar_index = len(self.klines)

        if self.setup_state == 1:
            bull_bo = tick_close > self.resistance * (Decimal('1') + self.breakout_buffer / Decimal('100'))
            bear_bo = tick_close < self.support * (Decimal('1') - self.breakout_buffer / Decimal('100'))
            
            contraction_ok = True
            if self.box_high1 is not None and (self.box_high1 - self.box_low1) > 0:
                current_range = max(x.high for x in self.klines[-self.min_cons_bars:]) - min(x.low for x in self.klines[-self.min_cons_bars:])
                contraction_ok = (current_range / (self.box_high1 - self.box_low1)) <= self.contraction_ratio
                
            if self.trend == 1 and bull_bo and contraction_ok:
                self.setup_state = 2
                self.accept_ct = 0
                self.bo_bar = bar_index
                logger.info("BULL_BREAKOUT", price=str(tick_close))
            elif self.trend == -1 and bear_bo and contraction_ok:
                self.setup_state = 2
                self.accept_ct = 0
                self.bo_bar = bar_index
                logger.info("BEAR_BREAKOUT", price=str(tick_close))
                
        elif self.setup_state == 2:
            if self.trend == 1 and tick_close > self.resistance:
                self.accept_ct += 1
                if self.accept_ct >= self.accept_bars:
                    self.setup_state = 3
                    self.rt_start_bar = bar_index
                    logger.info("ACCEPTANCE_REACHED")
            elif self.trend == 1 and tick_close < self.resistance:
                self.setup_state = 0
                self.accept_ct = 0
            elif self.trend == -1 and tick_close < self.support:
                self.accept_ct += 1
                if self.accept_ct >= self.accept_bars:
                    self.setup_state = 3
                    self.rt_start_bar = bar_index
                    logger.info("ACCEPTANCE_REACHED")
            elif self.trend == -1 and tick_close > self.support:
                self.setup_state = 0
                self.accept_ct = 0

        elif self.setup_state == 3:
            bars_since = bar_index - (self.rt_start_bar or bar_index)
            
            bull_rt = self.trend == 1 and tick_low <= self.resistance * (Decimal('1') + self.retest_buffer / Decimal('100')) and tick_close > self.resistance and tick_close > tick_open
            bear_rt = self.allow_shorts and self.trend == -1 and tick_high >= self.support * (Decimal('1') - self.retest_buffer / Decimal('100')) and tick_close < self.support and tick_close < tick_open
            
            if bull_rt:
                stop_cand = min(tick_low - self.atr * self.stop_atr_mult, self.resistance)
                min_dist = tick_close * self.min_stop_pct
                pending_stop = tick_close - min_dist if tick_close - stop_cand < min_dist else stop_cand
                self.setup_state = 0
                
                metadata = {
                    "pending_stop": pending_stop,
                    "target_r": self.target_r,
                    "atr_value": self.atr
                }
                logger.info("LONG_ENTRY_TRIGGERED", stop=str(pending_stop))
                return OrderSide.BUY, metadata
                
            elif bear_rt:
                stop_cand = max(tick_high + self.atr * self.stop_atr_mult, self.support)
                min_dist = tick_close * self.min_stop_pct
                pending_stop = tick_close + min_dist if stop_cand - tick_close < min_dist else stop_cand
                self.setup_state = 0
                
                metadata = {
                    "pending_stop": pending_stop,
                    "target_r": self.target_r,
                    "atr_value": self.atr
                }
                logger.info("SHORT_ENTRY_TRIGGERED", stop=str(pending_stop))
                return OrderSide.SELL, metadata
                
            if bars_since > self.retest_bars:
                self.setup_state = 0
                
        return None, {}
