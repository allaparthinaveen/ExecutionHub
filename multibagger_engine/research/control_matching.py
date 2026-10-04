import pandas as pd

def identify_control_group(df_with_returns, winners_df):
    """
    Finds 'Control' cases: stocks that had the exact same technical breakout
    (Close > SMA_200, Close > High_50, RVOL > 1.5) but FAILED to become multibaggers
    (i.e., their 3-year forward return was less than 50% or negative).
    """
    print("Identifying Control Group (Failed Breakouts)...")
    
    # We already have SMAs and RVOL in the df_with_returns from Phase 2
    # But wait, df_with_returns might not have them if they weren't saved back to the main df.
    # We need to re-calculate them or assume they are there.
    # To be safe, we will recalculate locally.
    
    # Sort
    df = df_with_returns.sort_values(by=['Symbol', 'Date']).copy()
    
    # 200-day SMA for Macro Trend
    df['SMA_200'] = df.groupby('Symbol')['Close'].transform(lambda x: x.rolling(window=200, min_periods=50).mean())
    # 50-day High for breakouts
    df['High_50'] = df.groupby('Symbol')['High'].transform(lambda x: x.rolling(window=50, min_periods=10).max().shift(1))
    # 50-day average volume
    df['Vol_Avg_50'] = df.groupby('Symbol')['Volume'].transform(lambda x: x.rolling(window=50, min_periods=10).mean().shift(1))
    # Relative Volume today
    df['RVOL'] = df['Volume'] / df['Vol_Avg_50']
    
    # Condition for Breakout
    df['Is_Breakout'] = (
        (df['Close'] > df['SMA_200']) & 
        (df['Close'] > df['High_50']) & 
        (df['RVOL'] >= 1.5)
    )
    
    breakouts = df[df['Is_Breakout']].copy()
    
    # Filter for BAD returns (Less than 50% over 3 years)
    failures = breakouts[breakouts['Forward_3Y_Return'] < 0.5].copy()
    
    # To avoid returning thousands of failures for the same symbol, just get one random failure per symbol
    # or the worst failure.
    worst_failures = failures.loc[failures.groupby('Symbol')['Forward_3Y_Return'].idxmin()]
    
    # Take a sample of 15 to match our 15 winners
    if len(worst_failures) > 15:
        sample_failures = worst_failures.sample(n=15, random_state=42)
    else:
        sample_failures = worst_failures
        
    records = []
    for _, row in sample_failures.iterrows():
        records.append({
            'Symbol': row['Symbol'],
            'Run_Start_Date': row['Date'],
            'Run_Start_Price': row['Close'],
            'RVOL_At_Entry': row['RVOL'],
            'Forward_3Y_Return': row['Forward_3Y_Return']
        })
        
    result_df = pd.DataFrame(records)
    print(f"Found {len(result_df)} distinct failed breakouts for the control group.")
    return result_df
