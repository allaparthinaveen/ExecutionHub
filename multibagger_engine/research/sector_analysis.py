import pandas as pd
import yfinance as yf
from pathlib import Path
import os

DATA_DIR = Path(__file__).parent.parent / "historical_data"

def fetch_market_index(period="10y"):
    """
    Fetches the NIFTY 50 index to act as the overall Market Regime proxy.
    """
    out_file = DATA_DIR / f"nifty50_{period}.csv"
    
    if out_file.exists():
        return pd.read_csv(out_file, parse_dates=['Date']).set_index('Date')
        
    print("Downloading NIFTY 50 historical data for Market Regime analysis...")
    nifty = yf.download("^NSEI", period=period, interval="1d", progress=False)
    
    if not nifty.empty:
        nifty.reset_index(inplace=True)
        nifty.to_csv(out_file, index=False)
        nifty.set_index('Date', inplace=True)
        
    return nifty

def analyze_market_regime(entries_df, nifty_df):
    """
    Determines the market/sector regime EXACTLY at the time of the entry breakout.
    """
    print("Analyzing Point-in-Time Market Regime (NIFTY 50)...")
    
    # Ensure timezone naive for matching
    nifty_df.index = pd.to_datetime(nifty_df.index, utc=True).tz_localize(None)
    
    regime_records = []
    
    for _, row in entries_df.iterrows():
        sym = row['Symbol']
        entry_date = pd.to_datetime(row['Entry_Date'], utc=True).tz_localize(None)
        
        try:
            # Look at NIFTY 50 up to the entry date
            nifty_history = nifty_df.loc[:entry_date]
            
            if len(nifty_history) < 126:
                continue
                
            current_nifty = nifty_history.iloc[-1]['Close']
            
            # Nifty 6-Month return prior to entry
            nifty_6m_ret = (current_nifty - nifty_history.iloc[-126]['Close']) / nifty_history.iloc[-126]['Close']
            nifty_6m_ret = float(nifty_6m_ret)
            
            # Simple Regime Definition
            if nifty_6m_ret > 0.10:
                regime = "Strong Bull"
            elif nifty_6m_ret > 0:
                regime = "Weak Bull"
            elif nifty_6m_ret > -0.10:
                regime = "Weak Bear"
            else:
                regime = "Deep Bear (Crash)"
                
        except Exception as e:
            regime = "Unknown"
            nifty_6m_ret = 0.0
            
        # Catalyst Mock for MVRD
        # In a real enterprise system, we would query GDELT for news articles published
        # about this ticker in the 30 days prior to entry_date.
        mock_catalyst = "Earnings Surge" if row['12M_Return_%'] > 50 else "Turnaround News" if row['12M_Return_%'] < 0 else "Unknown"
            
        regime_records.append({
            'Symbol': sym,
            'Entry_Date': entry_date,
            'NIFTY_6M_Return_%': round(nifty_6m_ret * 100, 2),
            'Market_Regime': regime,
            'Probable_Catalyst_Type (MVRD Mock)': mock_catalyst
        })
        
    return pd.DataFrame(regime_records)
