import os
import pandas as pd
import yfinance as yf
from pathlib import Path
import time

DATA_DIR = Path(__file__).parent.parent / "historical_data"

def download_historical_prices(universe, period="10y", interval="1d"):
    """
    Downloads historical OHLCV data for a given universe of tickers.
    Saves the output as a parquet file to avoid re-downloading on every run.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    out_file = DATA_DIR / f"ohlcv_{period}_{interval}.csv"
    
    if out_file.exists():
        print(f"Loading existing price data from {out_file}")
        return pd.read_csv(out_file, parse_dates=['Date'])
        
    print(f"Downloading {period} of data for {len(universe)} symbols...")
    
    # Download in bulk for speed
    raw_data = yf.download(
        tickers=" ".join(universe),
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False, # We want unadjusted closes for absolute breakout metrics, though we need adjusted for returns
        progress=True
    )
    
    # Re-structure multi-index columns for easier processing
    # If only 1 ticker is passed, yf returns single level. Handle multi-level:
    df_list = []
    
    if len(universe) > 1:
        for ticker in universe:
            if ticker in raw_data.columns.levels[0]:
                tdf = raw_data[ticker].copy()
                tdf.dropna(subset=['Close'], inplace=True)
                if not tdf.empty:
                    tdf['Symbol'] = ticker
                    df_list.append(tdf)
    else:
        tdf = raw_data.copy()
        tdf['Symbol'] = universe[0]
        df_list.append(tdf)
        
    if not df_list:
        print("Failed to download any valid data.")
        return pd.DataFrame()
        
    master_df = pd.concat(df_list)
    master_df.reset_index(inplace=True)
    
    print(f"Saving {len(master_df)} rows to {out_file}")
    master_df.to_csv(out_file, index=False)
    return master_df
