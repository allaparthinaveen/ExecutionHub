import sys
import os
import itertools
from datetime import datetime
from decimal import Decimal
import pandas as pd
import yfinance as yf
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.append(os.path.join(os.getcwd(), "trading_engine", "src"))

from trading_engine.execution.btc_signal_engine import BTCSignalEngine
from trading_engine.policies.btc_policy import BTCRegimeTrailingPolicy
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide, TrailingAction
from trading_engine.models.position import Position
from trading_engine.policies.base import TrailingState

def run_simulation_for_params(params, df_dict):
    min_cons_bars = params['min_cons_bars']
    stop_atr_mult = params['stop_atr_mult']
    trail_start_r = params['trail_start_r']
    target_r = params['target_r']

    engine = BTCSignalEngine(min_cons_bars=min_cons_bars, stop_atr_mult=Decimal(str(stop_atr_mult)))
    policy = BTCRegimeTrailingPolicy(
        target_r=Decimal(str(target_r)),
        move_be_at_r=Decimal(str(trail_start_r)),
        trail_start_r=Decimal(str(trail_start_r)),
        trail_atr_mult=Decimal('1.0'),
        stop_atr_mult=Decimal(str(stop_atr_mult)),
        use_fixed_target=False
    )

    balance = Decimal('1000.0')
    current_position = None
    current_state = None

    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_balance = float(balance)

    for i in range(len(df_dict['index'])):
        dt = df_dict['index'][i]
        o = df_dict['Open'][i]
        h = df_dict['High'][i]
        l = df_dict['Low'][i]
        c = df_dict['Close'][i]

        if current_position:
            price_path = [o, l, h, c] if c >= o else [o, h, l, c]

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
                    current_position.current_stop_loss = decision.proposed_stop
                    current_state.current_stop = decision.proposed_stop
                    
                elif decision.action == TrailingAction.CLOSE_POSITION:
                    entry = current_position.entry_price
                    exit_price = decision.proposed_stop 
                    side = current_position.side
                    
                    pnl_pct = (exit_price - entry) / entry if side == OrderSide.BUY else (entry - exit_price) / entry
                    pnl = pnl_pct * balance * Decimal('3') # Use 3x leverage / sizing
                    balance += pnl
                    
                    if float(balance) > peak_balance:
                        peak_balance = float(balance)
                    else:
                        dd = (peak_balance - float(balance)) / peak_balance * 100
                        if dd > max_drawdown:
                            max_drawdown = dd
                    
                    if pnl > 0: wins += 1
                    else: losses += 1
                    
                    current_position = None
                    current_state = None

        # Feed ticks for Signals
        ohlc_path = [o, l, h, c] if c >= o else [o, h, l, c]

        for i, tick in enumerate(ohlc_path):
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
                
                current_position = Position(
                    position_id=f"pos", symbol="BTCUSDT", side=signal, quantity=Decimal('1'),
                    entry_price=c_price, current_price=c_price,
                    highest_price_since_entry=c_price, lowest_price_since_entry=c_price,
                    opened_at=dt, updated_at=dt, broker="mock", account_id_hash="mock"
                )
                current_state = TrailingState(position_id=current_position.position_id)
                current_position.initial_stop_loss = ps
                current_position.current_stop_loss = ps
                current_state.current_stop = ps

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    net_return = (float(balance) - 1000) / 1000 * 100
    
    # Custom score: favors high return and decent win rate, punishes drawdowns heavily
    score = (net_return * win_rate) / (max_drawdown + 1) if total_trades >= 5 else 0

    return {
        **params,
        'trades': total_trades,
        'win_rate': round(win_rate, 1),
        'return_pct': round(net_return, 2),
        'max_dd_pct': round(max_drawdown, 2),
        'score': round(score, 2)
    }

def run_grid_search():
    print("Downloading 1 Year of BTC Data...")
    raw = yf.download(tickers="BTC-USD", period="1y", interval="1h", progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[['Open','High','Low','Close']].dropna()
    
    df_dict = {
        'index': df.index.tolist(),
        'Open': [Decimal(str(round(x, 2))) for x in df['Open']],
        'High': [Decimal(str(round(x, 2))) for x in df['High']],
        'Low': [Decimal(str(round(x, 2))) for x in df['Low']],
        'Close': [Decimal(str(round(x, 2))) for x in df['Close']]
    }
    
    grid = {
        'min_cons_bars': [6, 8, 12, 16],
        'stop_atr_mult': [1.0, 1.5, 2.0],
        'trail_start_r': [0.5, 1.0, 1.5],
        'target_r': [1.5, 2.0]
    }
    
    keys = grid.keys()
    combinations = [dict(zip(keys, v)) for v in itertools.product(*grid.values())]
    
    print(f"Starting grid search over {len(combinations)} combinations...")
    
    results = []
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(run_simulation_for_params, combo, df_dict): combo for combo in combinations}
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            
    res_df = pd.DataFrame(results)
    res_df = res_df.sort_values(by='score', ascending=False)
    
    print("\n=== TOP 5 PARAMETER COMBINATIONS ===")
    print(res_df.head(5).to_string(index=False))
    
    print("\n=== HIGHEST WIN RATE COMBINATIONS ===")
    print(res_df.sort_values(by='win_rate', ascending=False).head(5).to_string(index=False))

if __name__ == "__main__":
    run_grid_search()
