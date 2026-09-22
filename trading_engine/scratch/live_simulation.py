import sys
import os
import time
from datetime import datetime
from decimal import Decimal
import pandas as pd
import yfinance as yf

# Add src to python path so we can import our modules
sys.path.append(os.path.join(os.getcwd(), "trading_engine", "src"))

from trading_engine.execution.btc_signal_engine import BTCSignalEngine
from trading_engine.policies.btc_policy import BTCRegimeTrailingPolicy
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide, TrailingAction
from trading_engine.models.position import Position
from trading_engine.policies.base import TrailingState
from trading_engine.observability.notifications import TelegramNotificationProvider

def run_live_simulation():
    engine = BTCSignalEngine()
    policy = BTCRegimeTrailingPolicy()
    notifier = TelegramNotificationProvider()

    print("Fetching last 2 months of BTC data (Hourly)...")
    raw = yf.download(tickers="BTC-USD", period="60d", interval="1h", progress=False)
    if raw.empty:
        print("Failed to download data.")
        return
        
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[['Open','High','Low','Close']].dropna()
    print(f"Loaded {len(df)} hourly bars from {df.index[0].date()} to {df.index[-1].date()}")

    # Notify user that simulation is starting
    notifier.send_info(
        f"🧪 <b>Live Simulation Started</b>\n\n"
        f"Period: {df.index[0].date()} to {df.index[-1].date()}\n"
        f"Engine: BTC Regime Trailing\n"
        f"This will playback historical ticks and trigger actual notifications."
    )
    time.sleep(1) # rate limit protection

    current_position = None
    current_state = None

    wins = 0
    losses = 0
    trade_log = []

    for dt, row in df.iterrows():
        o = Decimal(str(round(float(row['Open']), 2)))
        h = Decimal(str(round(float(row['High']), 2)))
        l = Decimal(str(round(float(row['Low']), 2)))
        c = Decimal(str(round(float(row['Close']), 2)))

        # ─── Step 1: Manage Existing Position ───────────────
        if current_position:
            if c >= o:
                price_path = [o, l, h, c]
            else:
                price_path = [o, h, l, c]

            for tick in price_path:
                if current_position is None:
                    break
                    
                atr_val = engine.atr
                market = MarketState(
                    symbol="BTCUSDT", bid=tick, ask=tick, last=tick,
                    spread=Decimal('0.1'), timestamp=dt,
                    tick_size=Decimal('0.1'), point_size=Decimal('0.1'),
                    min_stop_distance=Decimal('5.0'),
                    atr_values={'atr14': atr_val} if atr_val else None
                )

                if current_state.highest_price is None or tick > current_state.highest_price:
                    current_state.highest_price = tick
                if current_state.lowest_price is None or tick < current_state.lowest_price:
                    current_state.lowest_price = tick
                
                current_position.current_price = tick
                decision = policy.evaluate(current_position, market, current_state)

                if decision.action == TrailingAction.MOVE_STOP:
                    old_stop = current_position.current_stop_loss
                    current_position.current_stop_loss = decision.proposed_stop
                    current_state.current_stop = decision.proposed_stop
                    
                    # SEND TELEGRAM NOTIFICATION (just like live!)
                    direction = "🔼" if current_position.side.value == "BUY" else "🔽"
                    unrealized = market.last - current_position.entry_price if current_position.side.value == "BUY" else current_position.entry_price - market.last
                    msg = (
                        f"🛡️ <b>Trailing SL Updated (Backtest)</b>\n\n"
                        f"Symbol: <b>BTCUSDT</b> {direction} {current_position.side.value}\n"
                        f"Current Price: <b>{market.last:.2f}</b>\n"
                        f"SL Moved: {old_stop:.2f} → <b>{decision.proposed_stop:.2f}</b>\n"
                        f"Unrealized P&L: {unrealized:+.2f} pts\n"
                        f"Reason: {decision.reason_code}"
                    )
                    notifier.send_info(msg)
                    print(f"[{dt}] Trailing SL Moved: {old_stop:.2f} -> {decision.proposed_stop:.2f} | Reason: {decision.reason_code}")
                    time.sleep(1)

                elif decision.action == TrailingAction.CLOSE_POSITION:
                    entry = current_position.entry_price
                    exit_price = decision.proposed_stop 
                    side = current_position.side
                    
                    pnl_pct = (exit_price - entry) / entry if side == OrderSide.BUY else (entry - exit_price) / entry
                    pnl = pnl_pct * Decimal('1000') # Base on $1000
                    
                    result = "WIN" if pnl > 0 else "LOSS"
                    if pnl > 0: wins += 1
                    else: losses += 1
                    
                    # SEND EXIT NOTIFICATION
                    direction = "🟢" if pnl > 0 else "🔴"
                    msg = (
                        f"{direction} <b>Position Closed (Backtest)</b>\n\n"
                        f"Symbol: <b>BTCUSDT</b>\n"
                        f"Side: {side.value}\n"
                        f"Entry: {entry:.2f}\n"
                        f"Exit: {exit_price:.2f}\n"
                        f"PnL: {pnl:+.2f} USD\n"
                        f"Reason: {decision.reason_code}"
                    )
                    notifier.send_info(msg)
                    print(f"[{dt}] CLOSED: {side.value} | Entry: {entry:.2f} | Exit: {exit_price:.2f} | PnL: {pnl:+.2f}")
                    time.sleep(1)

                    current_position = None
                    current_state = None

        # ─── Step 2: Feed ticks for Signals ───────────────
        if c >= o: ohlc_path = [o, l, h, c]
        else: ohlc_path = [o, h, l, c]

        for i, tick in enumerate(ohlc_path):
            is_close_tick = (i == len(ohlc_path) - 1)
            bar_market = MarketState(
                symbol="BTCUSDT", bid=tick, ask=tick, last=tick,
                spread=Decimal('0.1'), timestamp=dt,
                tick_size=Decimal('0.1'), point_size=Decimal('0.1'),
                min_stop_distance=Decimal('5.0')
            )

            signal, metadata = engine.evaluate(bar_market)

            if current_position is None and signal and 'pending_stop' in metadata:
                c_price = bar_market.last
                ps = metadata['pending_stop']
                risk = abs(c_price - ps)
                
                current_position = Position(
                    position_id=f"pos_{int(dt.timestamp())}",
                    symbol="BTCUSDT", side=signal, quantity=Decimal('1'),
                    entry_price=c_price, current_price=c_price,
                    highest_price_since_entry=c_price, lowest_price_since_entry=c_price,
                    opened_at=dt, updated_at=dt, broker="mock", account_id_hash="mock"
                )
                current_state = TrailingState(position_id=current_position.position_id)
                current_position.initial_stop_loss = ps
                current_position.current_stop_loss = ps
                current_state.current_stop = ps
                
                # SEND ENTRY NOTIFICATION
                target = c_price + (risk * Decimal('1.5')) if signal == OrderSide.BUY else c_price - (risk * Decimal('1.5'))
                msg = (
                    f"⚔️ <b>Engine Entry (Backtest)</b>\n\n"
                    f"Symbol: <b>BTCUSDT</b>\n"
                    f"Side: <b>{signal.name}</b>\n"
                    f"Fill Price: {c_price:.2f}\n"
                    f"Initial SL: {ps:.2f}\n"
                    f"Target (TP): {target:.2f}"
                )
                notifier.send_info(msg)
                print(f"[{dt}] ENTERED: {signal.name} @ {c_price:.2f} | SL: {ps:.2f}")
                time.sleep(1)

    notifier.send_info(f"✅ <b>Live Simulation Complete</b>\nTotal Trades: {wins+losses} ({wins}W/{losses}L)")
    print("Done!")

if __name__ == "__main__":
    run_live_simulation()
