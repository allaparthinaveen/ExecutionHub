import logging
import math
import requests
import pandas as pd
import io
import yfinance as yf
from typing import Dict, Any, List, Optional
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("nse_100_bagger.utils")

# Thread-safe local cache (10 minutes TTL)
info_cache = TTLCache(maxsize=200, ttl=600)
statements_cache = TTLCache(maxsize=200, ttl=600)
nse_symbols_cache = TTLCache(maxsize=1, ttl=86400)  # cache symbol list for 24 hours

def get_yf_ticker(symbol: str) -> yf.Ticker:
    """Instantiate a yfinance Ticker let it handle curl_cffi sessions internally."""
    return yf.Ticker(symbol)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def _fetch_ticker_info_raw(ticker_obj: yf.Ticker) -> Dict[str, Any]:
    """Scrape info raw from ticker."""
    return ticker_obj.info

def get_ticker_info(ticker_symbol: str) -> Dict[str, Any]:
    """Get cached or freshly fetched & fast_info enriched ticker info."""
    symbol = ticker_symbol.strip().upper()
    
    if symbol in info_cache:
        return info_cache[symbol]
        
    logger.info(f"Fetching fresh info from yfinance for {symbol}")
    ticker_obj = get_yf_ticker(symbol)
    
    try:
        info = _fetch_ticker_info_raw(ticker_obj)
        if not info or not isinstance(info, dict):
            logger.warning(f"yfinance returned empty or invalid metadata for {symbol}; using empty fallback.")
            info = {}
        else:
            info = dict(info)
            
        # Enrich with fast_info to bypass HTML rate limits/missing keys
        try:
            fast = ticker_obj.fast_info
            if not info.get("currentPrice"):
                info["currentPrice"] = fast.last_price
            if not info.get("marketCap"):
                info["marketCap"] = fast.market_cap
            if not info.get("sharesOutstanding"):
                info["sharesOutstanding"] = fast.shares
            if not info.get("currency"):
                info["currency"] = fast.currency
            if not info.get("longName") and not info.get("shortName"):
                info["longName"] = symbol
        except Exception as fe:
            logger.warning(f"Failed to enrich with fast_info for {symbol}: {fe}")
            
        info_cache[symbol] = info
        return info
    except Exception as e:
        logger.warning(f"Failed to fetch info for {symbol}; building fallback from fast_info: {e}")
        fallback_info = {}
        try:
            fast = ticker_obj.fast_info
            fallback_info["currentPrice"] = fast.last_price
            fallback_info["marketCap"] = fast.market_cap
            fallback_info["sharesOutstanding"] = fast.shares
            fallback_info["currency"] = fast.currency
            fallback_info["longName"] = symbol
        except Exception as fe:
            logger.warning(f"Failed to build fallback info from fast_info for {symbol}: {fe}")
        info_cache[symbol] = fallback_info
        return fallback_info

def get_ticker_statements(ticker_symbol: str) -> Dict[str, pd.DataFrame]:
    """Get annual financials, balance sheet, and cash flow statement."""
    symbol = ticker_symbol.strip().upper()
    
    if symbol in statements_cache:
        return statements_cache[symbol]
        
    logger.info(f"Fetching fresh financial statements from yfinance for {symbol}")
    ticker_obj = get_yf_ticker(symbol)
    
    try:
        financials = ticker_obj.financials
        balance_sheet = ticker_obj.balance_sheet
        cashflow = ticker_obj.cashflow
        
        statements = {
            "financials": financials if financials is not None else pd.DataFrame(),
            "balance_sheet": balance_sheet if balance_sheet is not None else pd.DataFrame(),
            "cashflow": cashflow if cashflow is not None else pd.DataFrame()
        }
        statements_cache[symbol] = statements
        return statements
    except Exception as e:
        logger.error(f"Failed to fetch financial statements for {symbol}: {e}")
        return {
            "financials": pd.DataFrame(),
            "balance_sheet": pd.DataFrame(),
            "cashflow": pd.DataFrame()
        }

def fetch_nse_symbols() -> List[str]:
    """
    Download and parse the official EQUITY_L.csv from the National Stock Exchange.
    Returns symbols for all common equities.
    """
    if "symbols" in nse_symbols_cache:
        return nse_symbols_cache["symbols"]
        
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    logger.info("Downloading active equities register from NSE archives...")
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        
        df = pd.read_csv(io.StringIO(res.text))
        # Ensure correct column headers by stripping whitespaces
        df.columns = [c.strip() for c in df.columns]
        
        # Filter for Series == 'EQ' (Common equities)
        eq_df = df[df["SERIES"].str.strip().str.upper() == "EQ"]
        symbols = sorted(eq_df["SYMBOL"].str.strip().tolist())
        
        if symbols:
            nse_symbols_cache["symbols"] = symbols
            return symbols
    except Exception as e:
        logger.error(f"Failed to download/parse NSE equity register: {e}")
        
    # Return a basic default backup list of major NSE symbols if download fails
    backup_list = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL",
        "SBI", "LICI", "ITC", "HINDUNILVR", "LT", "BAJFINANCE", "HCLTECH",
        "MARUTI", "SUNPHARMA", "ADANIENT", "KOTAKBANK", "TITAN", "AXISBANK",
        "DELHIVERY", "ZOMATO"
    ]
    return backup_list

def extract_statement_metric(df: pd.DataFrame, index_keys: List[str]) -> Optional[List[float]]:
    """Extract row values from financial statements using fallback name checks."""
    if df.empty:
        return None
    for k in index_keys:
        matching_rows = [idx for idx in df.index if str(idx).strip().lower() == k.lower()]
        if matching_rows:
            row = df.loc[matching_rows[0]]
            return [None if pd.isna(val) else float(val) for val in row]
    return None

def extract_float_metric(info: Dict[str, Any], keys: List[str], default: Optional[float] = None) -> Optional[float]:
    """Extract clean float metric from a dictionary fallback keys."""
    for k in keys:
        val = info.get(k)
        if val is not None:
            try:
                float_val = float(val)
                if not math.isnan(float_val):
                    return float_val
            except (ValueError, TypeError):
                pass
    return default
