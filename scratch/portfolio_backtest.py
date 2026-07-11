import os
import sys
import json
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

try:
    import psycopg2
except ImportError:
    psycopg2 = None

def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        if not psycopg2:
            print("ERROR: DATABASE_URL is set but 'psycopg2-binary' is not installed.")
            sys.exit(1)
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        print("Connecting to PostgreSQL database...")
        return psycopg2.connect(db_url)
    else:
        print("Connecting to local SQLite database: test_bagger_scan.db")
        return sqlite3.connect('test_bagger_scan.db')

def run_portfolio_backtest(start_year: int = 2022, total_investment: float = 50000.0):
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Fetch all High Potential candidates (passed candidates)
    cursor.execute("""
        SELECT ticker, company_name, score, label, metrics 
        FROM nse_bagger_scan_results 
        WHERE passed = True OR label = 'High Potential'
    """)
    records = cursor.fetchall()
    
    if not records:
        print(f"\nNo High Potential candidates found in the database. Please scan some stocks first!")
        conn.close()
        return
        
    print(f"\nFound {len(records)} passed High Potential candidates in database.")
    
    tickers = [r[0] for r in records]
    ticker_metadata = {r[0]: {"name": r[1], "score": r[2]} for r in records}
    
    # 2. Bulk download historical prices for start year (2022) and current prices
    print(f"Downloading historical price data from yfinance for {len(tickers)} tickers in bulk...")
    try:
        hist_data = yf.download(tickers=tickers, start=f"{start_year}-01-01", end=f"{start_year}-12-31")['Close']
        current_data = yf.download(tickers=tickers, period="5d")['Close']
    except Exception as e:
        print(f"Failed to fetch bulk price data: {e}")
        conn.close()
        return
        
    portfolio = []
    allocation_per_stock = total_investment / len(tickers)
    
    for ticker in tickers:
        name = ticker_metadata[ticker]["name"]
        score = ticker_metadata[ticker]["score"]
        
        # Calculate price in 2022 (mean price over the year)
        price_then = None
        if isinstance(hist_data, pd.DataFrame):
            if ticker in hist_data.columns:
                price_then = hist_data[ticker].dropna().mean()
        else:
            # Single ticker download returns Series
            price_then = hist_data.dropna().mean()
            
        # Get current price
        price_now = None
        if isinstance(current_data, pd.DataFrame):
            if ticker in current_data.columns:
                valid_prices = current_data[ticker].dropna()
                if not valid_prices.empty:
                    price_now = valid_prices.iloc[-1]
        else:
            valid_prices = current_data.dropna()
            if not valid_prices.empty:
                price_now = valid_prices.iloc[-1]
                
        if not price_then or not price_now or pd.isna(price_then) or pd.isna(price_now):
            print(f"  - Missing price data for {ticker}. Skipping from backtest.")
            continue
            
        multiple = price_now / price_then
        years_elapsed = datetime.now().year - start_year
        cagr = (multiple ** (1.0 / years_elapsed) - 1.0) * 100.0
        
        final_value = allocation_per_stock * multiple
        net_profit = final_value - allocation_per_stock
        
        portfolio.append({
            "ticker": ticker,
            "name": name,
            "score": score,
            "price_2022": price_then,
            "price_2026": price_now,
            "multiple": multiple,
            "cagr": cagr,
            "allocation": allocation_per_stock,
            "final_value": final_value,
            "profit": net_profit
        })
        
    if not portfolio:
        print("No valid price data resolved for any candidate.")
        conn.close()
        return
        
    df = pd.DataFrame(portfolio)
    total_final_value = df["final_value"].sum()
    total_profit = total_final_value - total_investment
    overall_multiple = total_final_value / total_investment
    overall_cagr = (overall_multiple ** (1.0 / years_elapsed) - 1.0) * 100.0
    
    print("\n" + "="*85)
    print(f"PORTFOLIO BACKTEST REPORT ({start_year} - {datetime.now().year})")
    print(f"Initial Investment: ₹{total_investment:,.2f} | Final Value: ₹{total_final_value:,.2f} | Net Profit: ₹{total_profit:,.2f}")
    print(f"Overall Return Multiple: {overall_multiple:.2f}x | Portfolio CAGR: {overall_cagr:.2f}%")
    print("="*85)
    
    headers = ["Ticker", "Company Name", "Buy Price (2022)", "Current Price (2026)", "Multiple", "CAGR", "Allocated (₹)", "Final Value (₹)"]
    print(f"{headers[0]:<15} | {headers[1]:<30} | {headers[2]:<16} | {headers[3]:<20} | {headers[4]:<8} | {headers[5]:<8} | {headers[6]:<13} | {headers[7]:<15}")
    print("-"*150)
    for p in portfolio:
        print(f"{p['ticker']:<15} | {p['name'][:30]:<30} | ₹{p['price_2022']:<15.2f} | ₹{p['price_2026']:<19.2f} | {p['multiple']:<8.2f}x | {p['cagr']:<7.1f}% | ₹{p['allocation']:<12,.2f} | ₹{p['final_value']:<14,.2f}")
    print("="*85)
    conn.close()

if __name__ == '__main__':
    run_portfolio_backtest()
