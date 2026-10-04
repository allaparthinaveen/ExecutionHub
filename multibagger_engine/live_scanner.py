import yfinance as yf
import pandas as pd
import numpy as np
from data.universe import get_mvrd_universe

def run_live_scanner():
    print("============================================================")
    print("PHASE 7: REAL-TIME LIVE SCANNER")
    print("============================================================")
    
    universe = get_mvrd_universe()
    print(f"Scanning {len(universe)} Indian equities for real-time multibagger setups...")
    
    # We only need the last 1-2 years of data for current setups
    print("Downloading latest market data...")
    raw_data = yf.download(" ".join(universe), period="2y", interval="1d", group_by="ticker", progress=False)
    
    live_setups = []
    
    for ticker in universe:
        try:
            # Handle yfinance multi-index vs single ticker dataframe
            if len(universe) > 1:
                if ticker not in raw_data.columns.levels[0]:
                    continue
                df = raw_data[ticker].copy()
            else:
                df = raw_data.copy()
                
            df.dropna(subset=['Close'], inplace=True)
            if len(df) < 252:
                continue # Need at least 1 year of data
                
            # Calculate Indicators
            df['SMA_200'] = df['Close'].rolling(window=200).mean()
            df['High_50'] = df['High'].rolling(window=50).max().shift(1)
            df['Vol_Avg_50'] = df['Volume'].rolling(window=50).mean().shift(1)
            df['RVOL'] = df['Volume'] / df['Vol_Avg_50']
            
            # Current Day Data
            today = df.iloc[-1]
            
            # Breakout Condition (What we proved in historical analysis)
            is_breakout = (
                (today['Close'] > today['SMA_200']) and 
                (today['Close'] > today['High_50']) and 
                (today['RVOL'] >= 1.5)
            )
            
            if is_breakout:
                # Calculate the ML Features
                current_price = today['Close']
                high_52w = df.iloc[-252:]['High'].max()
                dist_52w_high = (current_price - high_52w) / high_52w
                
                ret_12m = (current_price - df.iloc[-252]['Close']) / df.iloc[-252]['Close']
                ret_6m = (current_price - df.iloc[-126]['Close']) / df.iloc[-126]['Close']
                
                daily_returns = df.iloc[-252:]['Close'].pct_change().dropna()
                volatility_1y = daily_returns.std() * np.sqrt(252)
                
                # Check for "Late-Stage Exhaustion" flag
                # If 12M Return > 150%, flag it as high risk based on Phase 5 controls
                risk_flag = "⚠️ LATE-STAGE EXHAUSTION" if ret_12m > 1.5 else "✅ EARLY CYCLE"
                
                live_setups.append({
                    'Symbol': ticker,
                    'Price': round(current_price, 2),
                    'RVOL': round(today['RVOL'], 2),
                    'Dist_52W_High_%': round(dist_52w_high * 100, 2),
                    '6M_Return_%': round(ret_6m * 100, 2),
                    '12M_Return_%': round(ret_12m * 100, 2),
                    'Volatility_1Y_%': round(volatility_1y * 100, 2),
                    'Risk_Profile': risk_flag
                })
        except Exception as e:
            continue
            
    if len(live_setups) == 0:
        print("\nNo stocks in the MVRD universe met the strict multibagger criteria today.")
    else:
        results_df = pd.DataFrame(live_setups)
        results_df.sort_values(by='RVOL', ascending=False, inplace=True)
        
        
        print(f"\n🔥 {len(live_setups)} LIVE SETUPS DETECTED TODAY 🔥")
        print("============================================================")
        print(results_df.to_string(index=False))
        
    return live_setups

if __name__ == "__main__":
    run_live_scanner()
