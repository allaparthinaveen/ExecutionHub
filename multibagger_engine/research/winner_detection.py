import pandas as pd
import numpy as np

def calculate_rolling_returns(df, days=750):
    """
    Calculate rolling N-day returns (750 trading days ~= 3 years).
    We use Adj Close to account for splits and dividends over the 3-year period.
    """
    print(f"Calculating rolling {days}-day returns...")
    
    # Sort by Symbol and Date
    df = df.sort_values(by=['Symbol', 'Date']).copy()
    
    # Calculate the future 3-year return for every row (point in time)
    # We shift negative to look forward
    df['Future_3Y_AdjClose'] = df.groupby('Symbol')['Adj Close'].shift(-days)
    
    # Total return over the next 3 years
    df['Forward_3Y_Return'] = (df['Future_3Y_AdjClose'] - df['Adj Close']) / df['Adj Close']
    
    return df

def identify_multibagger_cohorts(df, min_return=3.0):
    """
    Identify rows where the forward 3-year return is >= min_return (e.g. 3.0 = 300% = 4x bagger).
    Returns a dataframe of identified "winner" entry points.
    """
    print(f"Identifying historical entry points yielding >= {min_return*100}% returns...")
    
    # Drop rows where we don't have 3 years of future data
    valid_df = df.dropna(subset=['Forward_3Y_Return']).copy()
    
    # Tag winners
    valid_df['Is_Winner'] = valid_df['Forward_3Y_Return'] >= min_return
    
    # Filter only winners
    winners = valid_df[valid_df['Is_Winner']]
    
    print(f"Found {len(winners)} point-in-time entries across {winners['Symbol'].nunique()} symbols that led to multibagger runs.")
    
    # To avoid overlapping dates for the same stock run, we can group by symbol and find the start of the massive run.
    # We'll identify continuous 'winner' periods and take the earliest date of that run.
    
    # Simplest logic for MVRD: just get the absolute best 3-year period for each stock that qualified
    best_entries = winners.loc[winners.groupby('Symbol')['Forward_3Y_Return'].idxmax()]
    
    return best_entries[['Date', 'Symbol', 'Close', 'Adj Close', 'Forward_3Y_Return']].sort_values(by='Forward_3Y_Return', ascending=False)
