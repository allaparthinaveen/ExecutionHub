"""
Ported from the legacy optimize_exits.py script.
Fits into the new research structure to help generate candidate models.
"""
import pandas as pd
import itertools
from pathlib import Path

def simulate_trade(tr, tp_points, t_start, t_step):
    """
    Simulation logic ported from legacy optimize_exits.py
    """
    direction = tr["direction"]
    entry = tr["fill_price"]
    initial_sl = tr["sl"]
    bars = tr["bars"]
    
    tp_price = entry + tp_points if direction == "LONG" else entry - tp_points
    current_sl = initial_sl
    
    for row in bars.itertuples():
        is_day_end = (row.hour_srv == 23)
        
        bid = row.bid_close
        ask = row.ask_close
        bid_h = row.bid_high
        bid_l = row.bid_low
        ask_h = row.ask_high
        ask_l = row.ask_low
        
        if direction == "LONG":
            if bid_l <= current_sl:
                return (current_sl - entry) - 0.10, "STOP_LOSS"
            if bid_h >= tp_price:
                return (tp_price - entry) - 0.10, "TAKE_PROFIT"
                
            profit_pts = bid_h - entry
            if profit_pts >= t_start:
                steps = int((profit_pts - t_start) / t_step)
                new_sl = entry + (steps * t_step)
                if new_sl > current_sl:
                    current_sl = new_sl
                    
            if is_day_end:
                return (bid - entry) - 0.10, "DAY_END"
                
        else:
            if ask_h >= current_sl:
                return (entry - current_sl) - 0.10, "STOP_LOSS"
            if ask_l <= tp_price:
                return (entry - tp_price) - 0.10, "TAKE_PROFIT"
                
            profit_pts = entry - ask_l
            if profit_pts >= t_start:
                steps = int((profit_pts - t_start) / t_step)
                new_sl = entry - (steps * t_step)
                if new_sl < current_sl:
                    current_sl = new_sl
                    
            if is_day_end:
                return (entry - ask) - 0.10, "DAY_END"
                
    last_row = bars.iloc[-1]
    if direction == "LONG":
        return (last_row["bid_close"] - entry) - 0.10, "DAY_END_FALLBACK"
    else:
        return (entry - last_row["ask_close"]) - 0.10, "DAY_END_FALLBACK"

def run_parameter_sweep(segments: list):
    """
    Runs trailing step/activation optimizations.
    """
    tps = [15, 20, 25, 30, 40, 50, 60]
    starts = [10, 15, 20]
    steps = [2, 5]
    
    combinations = list(itertools.product(tps, starts, steps))
    results = []
    
    for i, (tp, start, step) in enumerate(combinations):
        if start >= tp:
            continue
            
        total_pts = 0
        wins = 0
        for seg in segments:
            pts, reason = simulate_trade(seg, tp, start, step)
            total_pts += pts
            if pts > 0:
                wins += 1
                
        win_rate = (wins / len(segments)) * 100 if segments else 0
        
        results.append({
            "TP": tp,
            "Tr_Start": start,
            "Tr_Step": step,
            "Total_Pts": round(total_pts, 2),
            "WinRate": round(win_rate, 1)
        })
        
    df_res = pd.DataFrame(results)
    return df_res.sort_values(by="Total_Pts", ascending=False).reset_index(drop=True)
