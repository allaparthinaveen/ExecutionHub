import pandas as pd
import numpy as np

def calculate_technical_features(df):
    """
    Calculates point-in-time technical features required for entry detection.
    """
    print("Calculating technical features (SMAs, Highs, Volume)...")
    
    # Sort just in case
    df = df.sort_values(by=['Symbol', 'Date']).copy()
    
    # Calculate indicators per symbol
    # 200-day SMA for Macro Trend
    df['SMA_200'] = df.groupby('Symbol')['Close'].transform(lambda x: x.rolling(window=200, min_periods=50).mean())
    
    # 50-day High for breakouts
    df['High_50'] = df.groupby('Symbol')['High'].transform(lambda x: x.rolling(window=50, min_periods=10).max().shift(1))
    
    # 50-day average volume
    df['Vol_Avg_50'] = df.groupby('Symbol')['Volume'].transform(lambda x: x.rolling(window=50, min_periods=10).mean().shift(1))
    
    # Relative Volume today
    df['RVOL'] = df['Volume'] / df['Vol_Avg_50']
    
    return df

def detect_run_starts(df, winners_df):
    """
    Given a list of known winner periods, find the specific technical 'Entry Point'.
    We define a valid entry as:
    1. Close > SMA_200 (Macro Uptrend)
    2. Close > High_50 (Local Breakout)
    3. RVOL > 1.5 (Volume Expansion)
    
    We look for the FIRST date this happened within the 6 months PRIOR to the absolute best 3-year run,
    or during the first 3 months OF the run.
    """
    print("Detecting technical Run-Start entries for winners...")
    
    df = calculate_technical_features(df)
    
    # Define the breakout condition
    df['Is_Breakout'] = (
        (df['Close'] > df['SMA_200']) & 
        (df['Close'] > df['High_50']) & 
        (df['RVOL'] >= 1.5)
    )
    
    # Get all breakout dates
    breakouts = df[df['Is_Breakout']][['Date', 'Symbol', 'Close', 'RVOL']].copy()
    
    entry_records = []
    
    for _, winner in winners_df.iterrows():
        sym = winner['Symbol']
        best_date = winner['Date']
        
        # Lookback 6 months (approx 126 trading days) before the optimal 3Y start
        # and up to 3 months (approx 63 trading days) after it.
        start_window = best_date - pd.Timedelta(days=180)
        end_window = best_date + pd.Timedelta(days=90)
        
        # Find breakouts for this symbol in this window
        sym_breakouts = breakouts[
            (breakouts['Symbol'] == sym) & 
            (breakouts['Date'] >= start_window) & 
            (breakouts['Date'] <= end_window)
        ]
        
        if not sym_breakouts.empty:
            # The earliest breakout in this window is our detected Run-Start
            first_breakout = sym_breakouts.sort_values('Date').iloc[0]
            
            entry_records.append({
                'Symbol': sym,
                'Run_Start_Date': first_breakout['Date'],
                'Run_Start_Price': first_breakout['Close'],
                'RVOL_At_Entry': first_breakout['RVOL'],
                'Optimal_3Y_Date': best_date,
                'Optimal_3Y_Return': winner['Forward_3Y_Return']
            })
            
    result_df = pd.DataFrame(entry_records)
    print(f"Detected valid technical Run-Starts for {len(result_df)} out of {len(winners_df)} optimal winner periods.")
    return result_df
