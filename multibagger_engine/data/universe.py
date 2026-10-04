import pandas as pd
import requests
import io
import os
from pathlib import Path

# Fallback cache location
CACHE_DIR = Path(__file__).parent.parent / "historical_data"

def get_mvrd_universe():
    """
    Attempts to fetch the live NIFTY 500 list directly from the NSE archives.
    If the NSE blocks the request, it falls back to a cached version or the MVRD base list.
    We append '.NS' for Yahoo Finance compatibility.
    """
    try:
        # NSE blocks default user agents, so we spoof a standard browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text))
            tickers = df['Symbol'].tolist()
            
            # Cache it for future use just in case NSE goes down
            os.makedirs(CACHE_DIR, exist_ok=True)
            df.to_csv(CACHE_DIR / "ind_nifty500list_cache.csv", index=False)
            
            print(f"Successfully fetched {len(tickers)} symbols from NSE Nifty 500.")
            return [f"{str(t).strip()}.NS" for t in tickers]
            
    except Exception as e:
        print(f"Warning: Failed to fetch live NIFTY 500 from NSE ({e}). Checking cache...")
        
    # Try cache
    try:
        cache_file = CACHE_DIR / "ind_nifty500list_cache.csv"
        if cache_file.exists():
            df = pd.read_csv(cache_file)
            tickers = df['Symbol'].tolist()
            print(f"Loaded {len(tickers)} symbols from local cache.")
            return [f"{str(t).strip()}.NS" for t in tickers]
    except Exception:
        pass
        
    print("Warning: Falling back to static MVRD list.")
    base_tickers = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", 
        "SBIN", "BHARTIARTL", "KOTAKBANK", "BAJFINANCE", "LARSEN", "ASIANPAINT", 
        "AXISBANK", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJAJFINSV", 
        "WIPRO", "NESTLEIND", "ONGC", "JSWSTEEL", "NTPC", "TATAMOTORS", 
        "TATASTEEL", "POWERGRID", "M&M", "HCLTECH", "ADANIENT", "COALINDIA", 
        "TECHM", "BRITANNIA", "BAJAJ-AUTO", "GRASIM", "HINDALCO", "INDUSINDBK", 
        "EICHERMOT", "DIVISLAB", "APOLLOHOSP", "DRREDDY", "TATACONSUM", "CIPLA", 
        "BPCL", "HEROMOTOCO", "UPL", "ADANIPORTS", "HDFCLIFE", "SBILIFE", "TRENT",
        "DIXON", "POLYCAB", "DEEPAKNTR", "NAVINFLUOR", "LAURUSLABS", "TATAELXSI",
        "KPITTECH", "CGPOWER", "RVNL", "MAZDOCK", "HAL"
    ]
    return [f"{t}.NS" for t in base_tickers]
