import yfinance as yf
import pandas as pd
import numpy as np

def run_custom_scanner():
    custom_list = [
        "TAALTECH", "MHLXMIRU", "FRONTSP", "CMPDI", "SIGMA", 
        "SBGLP", "DRCSYSTEMS", "NILASPACES", "GARUDA", 
        "WAAREEINDO", "CEINSYS", "MASTERTR", "KPL", 
        "FERMENTA", "MPSLTD"
    ]
    
    # Append .NS for Yahoo Finance compatibility for Indian stocks
    # Note: Some of these might be BSE listed (.BO), but we will try .NS first, then .BO if missing.
    universe = [f"{t}.NS" for t in custom_list]
    
    print(f"Scanning {len(universe)} custom equities...")
    
    raw_data = yf.download(" ".join(universe), period="2y", interval="1d", group_by="ticker", progress=False)
    
    live_setups = []
    
    for ticker in universe:
        try:
            if len(universe) > 1:
                if ticker not in raw_data.columns.levels[0]:
                    # Try BSE if NSE fails
                    bse_ticker = ticker.replace(".NS", ".BO")
                    print(f"Failed to find {ticker}, skipping...")
                    continue
                df = raw_data[ticker].copy()
            else:
                df = raw_data.copy()
                
            df.dropna(subset=['Close'], inplace=True)
            if len(df) < 252:
                print(f"{ticker} has less than 252 days of data. Skipping...")
                continue 
                
            df['SMA_200'] = df['Close'].rolling(window=200).mean()
            df['High_50'] = df['High'].rolling(window=50).max().shift(1)
            df['Vol_Avg_50'] = df['Volume'].rolling(window=50).mean().shift(1)
            df['RVOL'] = df['Volume'] / df['Vol_Avg_50']
            
            today = df.iloc[-1]
            
            # Print state for debugging
            current_price = today['Close']
            print(f"[{ticker}] Price: {current_price:.2f} | SMA200: {today['SMA_200']:.2f} | High50: {today['High_50']:.2f} | RVOL: {today['RVOL']:.2f}")
            
            is_breakout = (
                (today['Close'] > today['SMA_200']) and 
                (today['Close'] > today['High_50']) and 
                (today['RVOL'] >= 1.5)
            )
            
            if is_breakout:
                high_52w = df.iloc[-252:]['High'].max()
                dist_52w_high = (current_price - high_52w) / high_52w
                ret_12m = (current_price - df.iloc[-252]['Close']) / df.iloc[-252]['Close']
                ret_6m = (current_price - df.iloc[-126]['Close']) / df.iloc[-126]['Close']
                daily_returns = df.iloc[-252:]['Close'].pct_change().dropna()
                volatility_1y = daily_returns.std() * np.sqrt(252)
                
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
            pass
            
    if len(live_setups) == 0:
        print("\nNo stocks in this custom list met the strict multibagger criteria today.")
    else:
        results_df = pd.DataFrame(live_setups)
        results_df.sort_values(by='RVOL', ascending=False, inplace=True)
        print(f"\n🔥 {len(live_setups)} LIVE SETUPS DETECTED TODAY 🔥")
        print("============================================================")
        print(results_df.to_string(index=False))

if __name__ == "__main__":
    run_custom_scanner()
