import os
import sys
from decimal import Decimal
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd

sys.path.append(os.path.join(os.getcwd(), "trading_engine", "src"))

from trading_engine.models.enums import OrderSide, TrailingAction, PositionStatus
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.policies.samurai import SamuraiTrailingPolicy
from trading_engine.policies.base import TrailingState

class MockBroker:
    def __init__(self, df_daily):
        self.df_daily = df_daily
        
    def get_previous_daily_high_low(self, symbol):
        # We simulate the previous day's high/low being passed in beforeevaluate
        return self.hl_override

def run_samurai_backtest():
    print("Downloading 10 days of XAU (Gold) Data...")
    raw = yf.download(tickers="GC=F", period="10d", interval="1h", progress=False)
    
    if raw.empty:
        print("Failed to download data.")
        return
        
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    # Get daily data for actual high/low computation
    daily_raw = yf.download(tickers="GC=F", period="15d", interval="1d", progress=False)
    df_daily = daily_raw.copy()
    if isinstance(df_daily.columns, pd.MultiIndex):
        df_daily.columns = df_daily.columns.droplevel(1)

    # Convert timezone to naive
    df.index = df.index.tz_localize(None)
    df_daily.index = df_daily.index.tz_localize(None)

    broker = MockBroker(df_daily)
    policy = SamuraiTrailingPolicy(activation_pts=Decimal('0.5'), step_pts=Decimal('0.2'))
    
    balance = Decimal('1000.0')
    current_position = None
    current_state = None
    
    trades = []
    
    straddle_armed = False
    daily_high = None
    daily_low = None
    last_day = None

    for idx, row in df.iterrows():
        dt = idx
        current_day = dt.date()
        c = Decimal(str(row['Close']))
        
        # New Day logic
        if current_day != last_day:
            # Find previous day in df_daily
            past_days = df_daily[df_daily.index.date < current_day]
            if not past_days.empty:
                prev_day = past_days.iloc[-1]
                daily_high = Decimal(str(prev_day['High']))
                daily_low = Decimal(str(prev_day['Low']))
                straddle_armed = True
            last_day = current_day
            
        market = MarketState(
            symbol="XAUUSDT",
            bid=c,
            ask=c,
            last=c,
            spread=Decimal('0'),
            timestamp=dt,
            tick_size=Decimal('0.01'),
            point_size=Decimal('0.01'),
            min_stop_distance=Decimal('0.5')
        )
        
        # Engine Logic
        signal = None
        if current_position is None and straddle_armed and daily_high and daily_low:
            if c > daily_high:
                signal = OrderSide.BUY
                straddle_armed = False
            elif c < daily_low:
                signal = OrderSide.SELL
                straddle_armed = False
                
        # Execution
        if signal:
            # Micro lot size
            qty = Decimal('0.01')
            initial_sl = c - Decimal('2.0') if signal == OrderSide.BUY else c + Decimal('2.0')
            current_position = Position(
                position_id=f"pos_{int(dt.timestamp())}",
                symbol="XAUUSDT",
                side=signal,
                quantity=qty,
                entry_price=c,
                current_price=c,
                highest_price_since_entry=c,
                lowest_price_since_entry=c,
                opened_at=dt,
                updated_at=dt,
                broker="backtest",
                account_id_hash="backtest",
                status=PositionStatus.OPEN,
                initial_stop_loss=initial_sl,
                current_stop_loss=initial_sl
            )
            current_state = TrailingState(position_id=current_position.position_id)
            current_state.current_stop = initial_sl
            
        # Management
        if current_position:
            current_position.current_price = c
            decision = policy.evaluate(current_position, market, current_state)
            
            if current_position.side == OrderSide.BUY and c <= current_position.current_stop_loss:
                decision.action = TrailingAction.CLOSE_POSITION
                decision.reason_code = "STOP_HIT"
                decision.proposed_stop = current_position.current_stop_loss
            elif current_position.side == OrderSide.SELL and c >= current_position.current_stop_loss:
                decision.action = TrailingAction.CLOSE_POSITION
                decision.reason_code = "STOP_HIT"
                decision.proposed_stop = current_position.current_stop_loss
                
            if decision.action in (TrailingAction.MOVE_STOP, TrailingAction.MOVE_TO_BREAKEVEN):
                current_position.current_stop_loss = decision.proposed_stop
                current_state.current_stop = decision.proposed_stop
                
            if decision.action == TrailingAction.CLOSE_POSITION:
                exit_price = decision.proposed_stop if decision.proposed_stop else c
                pnl = (exit_price - current_position.entry_price) * qty if current_position.side == OrderSide.BUY else (current_position.entry_price - exit_price) * qty
                balance += pnl
                trades.append({
                    'entry_dt': current_position.opened_at,
                    'exit_dt': dt,
                    'side': current_position.side.name,
                    'entry_price': current_position.entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'reason': decision.reason_code
                })
                current_position = None

    print(f"\n{'='*50}")
    print(f"  Samurai True Straddle — 10-Day Backtest")
    print(f"{'='*50}")
    print(f"  Start Bal   : $1,000.00")
    print(f"  End Bal     : ${balance:,.2f}")
    
    wins = len([t for t in trades if t['pnl'] > 0])
    losses = len([t for t in trades if t['pnl'] <= 0])
    total = len(trades)
    wr = (wins / total * 100) if total > 0 else 0
    print(f"  Win Rate    : {wr:.1f}% ({wins}W / {losses}L)")
    print(f"{'='*50}")
    
    for t in trades:
        print(f"  {t['entry_dt'].strftime('%b %d')} | {t['side']} | Entry: {t['entry_price']:.2f} | Exit: {t['exit_price']:.2f} | PnL: ${t['pnl']:.2f} | {t['reason']}")

if __name__ == "__main__":
    run_samurai_backtest()
