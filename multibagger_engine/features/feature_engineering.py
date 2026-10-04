import pandas as pd
import numpy as np
import yfinance as yf

def calculate_entry_features(prices_df, entries_df):
    """
    Calculates quantitative features (technical and fundamental) at the exact point-in-time
    of the historical run-start date to avoid look-ahead bias.
    """
    print("Calculating point-in-time quantitative features at Entry...")
    
    # Sort prices
    prices_df = prices_df.sort_values(by=['Symbol', 'Date']).copy()
    prices_df.set_index(['Symbol', 'Date'], inplace=True)
    
    feature_records = []
    
    # We will fetch current fundamentals as a proxy since true historical point-in-time
    # fundamentals require a paid enterprise API (like EODHD or FactSet).
    # We mark them explicitly as DATA-LIMITED.
    print("WARNING: Using current fundamentals as a proxy for historical point-in-time. [DATA-LIMITED]")
    
    # Cache fundamentals to avoid hitting the API too much
    fundamentals_cache = {}
    
    for _, row in entries_df.iterrows():
        sym = row['Symbol']
        entry_date = row['Run_Start_Date']
        
        # 1. TECHNICAL FEATURES (True Point-In-Time)
        try:
            # Get data up to the entry date
            history = prices_df.loc[sym].loc[:entry_date]
            
            if len(history) < 252:
                continue # Need at least 1 year of history
                
            current_price = history.iloc[-1]['Close']
            
            # 52-week high/low (approx 252 trading days)
            high_52w = history.iloc[-252:]['High'].max()
            low_52w = history.iloc[-252:]['Low'].min()
            
            dist_52w_high = (current_price - high_52w) / high_52w
            dist_52w_low = (current_price - low_52w) / low_52w
            
            # Returns prior to entry
            ret_1m = (current_price - history.iloc[-21]['Close']) / history.iloc[-21]['Close']
            ret_3m = (current_price - history.iloc[-63]['Close']) / history.iloc[-63]['Close']
            ret_6m = (current_price - history.iloc[-126]['Close']) / history.iloc[-126]['Close']
            ret_12m = (current_price - history.iloc[-252]['Close']) / history.iloc[-252]['Close']
            
            # Volatility (Annualized)
            daily_returns = history.iloc[-252:]['Close'].pct_change().dropna()
            volatility_1y = daily_returns.std() * np.sqrt(252)
            
        except Exception as e:
            print(f"Error calculating technicals for {sym}: {e}")
            continue
            
        # 2. FUNDAMENTAL FEATURES (Mocked with Current Data)
        if sym not in fundamentals_cache:
            try:
                ticker = yf.Ticker(sym)
                info = ticker.info
                fundamentals_cache[sym] = {
                    'ROE_%': info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None,
                    'OperatingMargin_%': info.get('operatingMargins', 0) * 100 if info.get('operatingMargins') else None,
                    'Debt_To_Equity': info.get('debtToEquity', None),
                    'Revenue_Growth_%': info.get('revenueGrowth', 0) * 100 if info.get('revenueGrowth') else None
                }
            except:
                fundamentals_cache[sym] = {'ROE_%': None, 'OperatingMargin_%': None, 'Debt_To_Equity': None, 'Revenue_Growth_%': None}
                
        fund = fundamentals_cache[sym]
        
        # Build the feature row
        record = {
            'Symbol': sym,
            'Entry_Date': entry_date,
            'Dist_52W_High_%': round(dist_52w_high * 100, 2),
            'Dist_52W_Low_%': round(dist_52w_low * 100, 2),
            '1M_Return_%': round(ret_1m * 100, 2),
            '6M_Return_%': round(ret_6m * 100, 2),
            '12M_Return_%': round(ret_12m * 100, 2),
            'Volatility_1Y_%': round(volatility_1y * 100, 2),
            **fund
        }
        
        feature_records.append(record)
        
    return pd.DataFrame(feature_records)
