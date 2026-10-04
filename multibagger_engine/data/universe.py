def get_mvrd_universe():
    """
    Returns a representative sample of NSE stocks for the Minimum Viable Research Dataset.
    In a full production run, this would query a database for all historical NSE/BSE tickers.
    We append '.NS' for Yahoo Finance compatibility.
    """
    base_tickers = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", 
        "SBIN", "BHARTIARTL", "KOTAKBANK", "BAJFINANCE", "LARSEN", "ASIANPAINT", 
        "AXISBANK", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJAJFINSV", 
        "WIPRO", "NESTLEIND", "ONGC", "JSWSTEEL", "NTPC", "TATAMOTORS", 
        "TATASTEEL", "POWERGRID", "M&M", "HCLTECH", "ADANIENT", "COALINDIA", 
        "TECHM", "BRITANNIA", "BAJAJ-AUTO", "GRASIM", "HINDALCO", "INDUSINDBK", 
        "EICHERMOT", "DIVISLAB", "APOLLOHOSP", "DRREDDY", "TATACONSUM", "CIPLA", 
        "BPCL", "HEROMOTOCO", "UPL", "ADANIPORTS", "HDFCLIFE", "SBILIFE", "TRENT",
        # Adding some known historical multibaggers from mid/small cap for robust testing
        "DIXON", "POLYCAB", "DEEPAKNTR", "NAVINFLUOR", "LAURUSLABS", "TATAELXSI",
        "KPITTECH", "CGPOWER", "RVNL", "MAZDOCK", "HAL"
    ]
    
    return [f"{t}.NS" for t in base_tickers]
