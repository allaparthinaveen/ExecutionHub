import os
import sys
import time
import math
import pandas as pd
import yfinance as yf
from datetime import datetime

# Ensure project root is in search path
project_root = "/Users/naveenallaparthi/github/ExecutionHub"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.services.yahoo_client import YahooFinanceClient, get_yf_ticker
from app.schemas.bagger import BaggerFilterConfig, YearlyMetric, StockMetrics
from app.services.bagger_scanner import BaggerScannerService

def get_historical_price(ticker_obj: yf.Ticker, year: int) -> float:
    """Fetch average closing price of a stock in a given historical year."""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    try:
        hist = ticker_obj.history(start=start_date, end=end_date)
        if not hist.empty:
            return float(hist['Close'].mean())
    except Exception:
        pass
    return None

def backtest_ticker(symbol: str, backtest_year: int = 2016) -> dict:
    """
    Simulates running the 100-bagger screening rules on a ticker as of a historical year,
    and returns its subsequent actual performance up to today.
    """
    yf_symbol = symbol.strip().upper()
    if not yf_symbol.endswith(".NS") and not yf_symbol.endswith(".BO"):
        yf_symbol = f"{yf_symbol}.NS"
        
    print(f"\nProcessing {yf_symbol}...")
    ticker_obj = get_yf_ticker(yf_symbol)
    
    # 1. Fetch current price and historical price at backtest year
    price_then = get_historical_price(ticker_obj, backtest_year)
    
    # Get current price
    try:
        price_now = ticker_obj.fast_info.last_price
    except Exception:
        try:
            hist_now = ticker_obj.history(period="5d")
            price_now = float(hist_now['Close'].iloc[-1])
        except Exception:
            price_now = None
            
    if not price_then or not price_now:
        print(f"  - Missing price history (Then: {price_then}, Now: {price_now}). Skipping.")
        return None
        
    # Calculate actual return
    total_return_ratio = price_now / price_then
    years_elapsed = datetime.now().year - backtest_year
    annualized_return = (total_return_ratio ** (1.0 / years_elapsed) - 1.0) * 100.0
    
    # 2. Reconstruct historical financials as they stood in the backtest year
    try:
        financials = ticker_obj.financials
        balance_sheet = ticker_obj.balance_sheet
        cashflow = ticker_obj.cashflow
        info = ticker_obj.info
    except Exception as e:
        print(f"  - Failed to fetch statements for {yf_symbol}: {e}")
        return None
        
    # Filter statement DataFrames to only include years <= backtest_year
    def filter_df_by_year(df: pd.DataFrame, max_year: int) -> pd.DataFrame:
        if df.empty:
            return df
        cols_to_keep = []
        for col in df.columns:
            try:
                col_year = pd.to_datetime(col).year
                if col_year <= max_year:
                    cols_to_keep.append(col)
            except Exception:
                pass
        return df[cols_to_keep]
        
    hist_fin = filter_df_by_year(financials, backtest_year)
    hist_bs = filter_df_by_year(balance_sheet, backtest_year)
    hist_cf = filter_df_by_year(cashflow, backtest_year)
    
    if hist_fin.empty:
        print(f"  - No financial history up to {backtest_year}. Skipping.")
        return None
        
    # Reconstruct historical metrics
    rev_rows = ["Total Revenue", "Operating Revenue", "Revenue"]
    rev_vals = YahooFinanceClient.extract_statement_metric(hist_fin, rev_rows)
    revenue_history = []
    if rev_vals:
        years = [pd.to_datetime(col).year for col in hist_fin.columns]
        for yr, val in zip(years, rev_vals):
            if yr and val and val > 0:
                revenue_history.append(YearlyMetric(year=int(yr), value=float(val)))
                
    eps_rows = ["Diluted EPS", "Basic EPS"]
    eps_vals = YahooFinanceClient.extract_statement_metric(hist_fin, eps_rows)
    eps_history = []
    if eps_vals:
        years = [pd.to_datetime(col).year for col in hist_fin.columns]
        for yr, val in zip(years, eps_vals):
            if yr and val is not None:
                eps_history.append(YearlyMetric(year=int(yr), value=float(val)))
                
    # Historical market cap (approximated from shares outstanding and price then)
    shares = info.get("sharesOutstanding")
    mcap_then = shares * price_then if shares else info.get("marketCap")
    if mcap_then and price_now and price_then:
        # Scale back market cap to then
        mcap_then = (mcap_then / price_now) * price_then
        
    # Historical Debt/Equity
    debt_to_equity = None
    try:
        total_debt_list = YahooFinanceClient.extract_statement_metric(hist_bs, ["Total Debt", "Net Debt"])
        equity_list = YahooFinanceClient.extract_statement_metric(hist_bs, ["Stockholders Equity", "Common Stock Equity"])
        if total_debt_list and equity_list and equity_list[0] and equity_list[0] > 0:
            debt_to_equity = total_debt_list[0] / equity_list[0]
    except Exception:
        pass
        
    # Historical Cash Flow Quality
    ocf_to_net_income_ratio = None
    try:
        ocf_rows = ["Operating Cash Flow", "Cash Flow From Operating Activities", "Total Cash From Operating Activities"]
        ocf_vals = YahooFinanceClient.extract_statement_metric(hist_cf, ocf_rows)
        net_income_vals = YahooFinanceClient.extract_statement_metric(hist_fin, ["Net Income", "Net Income From Continuing Operations"])
        if ocf_vals and net_income_vals:
            ratios = []
            for ocf, ni in zip(ocf_vals, net_income_vals):
                if ni and ni > 0 and ocf is not None:
                    ratios.append(ocf / ni)
            if ratios:
                ocf_to_net_income_ratio = sum(ratios) / len(ratios)
    except Exception:
        pass
        
    # Build historical metrics profile
    hist_metrics = StockMetrics(
        ticker=yf_symbol,
        company_name=info.get("longName") or yf_symbol,
        market_cap=mcap_then,
        current_price=price_then,
        trailing_pe=info.get("trailingPE"), # Approximated from current info
        forward_pe=None,
        roe=info.get("returnOnEquity") * 100.0 if info.get("returnOnEquity") else 15.0, # Default safe ROE for simulation
        operating_margin=info.get("operatingMargins") * 100.0 if info.get("operatingMargins") else 12.0,
        debt_to_equity=debt_to_equity,
        promoter_holding=info.get("heldPercentInsiders") * 100.0 if info.get("heldPercentInsiders") else 45.0,
        ocf_to_net_income_ratio=ocf_to_net_income_ratio or 1.0, # Fallback to passed
        pledged_percentage=0.0,
        revenue_history=revenue_history,
        eps_history=eps_history
    )
    
    # Run the rule checks
    config = BaggerFilterConfig(max_market_cap_inr=100000000000.0) # Larger size buffer for historical backtest comparison
    candidate = BaggerScannerService.evaluate_candidate(hist_metrics, config)
    
    print(f"  - Price in {backtest_year}: INR {price_then:.2f}")
    print(f"  - Price Today: INR {price_now:.2f}")
    print(f"  - Actual Return: {total_return_ratio:.2f}x (CAGR: {annualized_return:.2f}%)")
    print(f"  - 100-Bagger Screen Result: {candidate.label} (Score: {candidate.score:.1f}%)")
    
    return {
        "ticker": yf_symbol,
        "name": hist_metrics.company_name,
        "passed": candidate.passed,
        "label": candidate.label,
        "score": candidate.score,
        "price_then": price_then,
        "price_now": price_now,
        "multiple": total_return_ratio,
        "cagr": annualized_return
    }

def run_backtest():
    # Test universe (mix of historical high compounders and benchmark stocks)
    universe = [
        "ASTRAL.NS",       # Moat PVC Pipes compounding star
        "TATAELXSI.NS",   # High ROE tech compounder
        "RELIANCE.NS",    # Giant cap (benchmark comparison)
        "20MICRONS.NS",   # Average small-cap
        "3MINDIA.NS"      # High PE MNC
    ]
    
    backtest_year = 2022
    results = []
    
    print(f"=== STARTING HISTORICAL 100-BAGGER BACKTEST (START YEAR: {backtest_year}) ===")
    for ticker in universe:
        try:
            res = backtest_ticker(ticker, backtest_year)
            if res:
                results.append(res)
            time.sleep(1) # Sleep to avoid rate limits
        except Exception as e:
            print(f"Error backtesting {ticker}: {e}")
            
    if not results:
        print("No backtest results generated.")
        return
        
    df = pd.DataFrame(results)
    print("\n\n========================= BACKTEST REPORT =========================")
    print(df.to_string(index=False, columns=["ticker", "name", "passed", "label", "score", "multiple", "cagr"]))
    print("==================================================================")
    
    # Calculate performance comparison
    passed_portfolio = df[df["passed"] == True]
    failed_portfolio = df[df["passed"] == False]
    
    print("\nPerformance Summary:")
    if not passed_portfolio.empty:
        avg_passed_return = passed_portfolio["multiple"].mean()
        print(f"  - PASSED Candidates Avg Return: {avg_passed_return:.2f}x")
    else:
        print("  - No candidates passed the screen in 2016.")
        
    if not failed_portfolio.empty:
        avg_failed_return = failed_portfolio["multiple"].mean()
        print(f"  - FAILED Candidates Avg Return: {avg_failed_return:.2f}x")

if __name__ == '__main__':
    run_backtest()
