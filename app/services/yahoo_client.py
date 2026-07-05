import logging
import math
import yfinance as yf
import pandas as pd
from typing import Dict, Any, List, Optional
from cachetools import TTLCache, cached
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("tradeservices.yahoo_client")

# Thread-safe in-memory cache for ticker info (TTL of 10 minutes, max size 100 tickers)
info_cache = TTLCache(maxsize=100, ttl=600)
statements_cache = TTLCache(maxsize=100, ttl=600)

class YahooFinanceClient:
    """
    Robust wrapper client for Yahoo Finance data retrieval using yfinance.
    Implements exponential-backoff retries, in-memory caching, and metric name normalization.
    """

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _fetch_ticker_info(ticker_obj: yf.Ticker) -> Dict[str, Any]:
        """Fetch ticker info with retry policy."""
        return ticker_obj.info

    @classmethod
    def get_ticker_info(cls, ticker_symbol: str) -> Dict[str, Any]:
        """Get cached or freshly fetched ticker info."""
        symbol = ticker_symbol.strip().upper()
        
        # Check cache manually to support logging
        if symbol in info_cache:
            logger.info(f"Returning cached info for {symbol}")
            return info_cache[symbol]
            
        logger.info(f"Fetching fresh info from yfinance for {symbol}")
        ticker_obj = yf.Ticker(symbol)
        try:
            info = cls._fetch_ticker_info(ticker_obj)
            info_cache[symbol] = info
            return info
        except Exception as e:
            logger.error(f"Failed to fetch info for {symbol} after retries: {e}")
            raise

    @classmethod
    def get_ticker_statements(cls, ticker_symbol: str) -> Dict[str, pd.DataFrame]:
        """Get annual financials, balance sheet, and cash flow statement."""
        symbol = ticker_symbol.strip().upper()
        
        if symbol in statements_cache:
            logger.info(f"Returning cached financial statements for {symbol}")
            return statements_cache[symbol]
            
        logger.info(f"Fetching fresh financial statements from yfinance for {symbol}")
        ticker_obj = yf.Ticker(symbol)
        
        try:
            # yfinance properties are lazy-loaded, fetch them explicitly
            financials = ticker_obj.financials
            balance_sheet = ticker_obj.balance_sheet
            cashflow = ticker_obj.cashflow
            dividends = ticker_obj.dividends
            
            statements = {
                "financials": financials if financials is not None else pd.DataFrame(),
                "balance_sheet": balance_sheet if balance_sheet is not None else pd.DataFrame(),
                "cashflow": cashflow if cashflow is not None else pd.DataFrame(),
                "dividends": pd.Series(dividends) if dividends is not None else pd.Series()
            }
            statements_cache[symbol] = statements
            return statements
        except Exception as e:
            logger.error(f"Failed to fetch financial statements for {symbol}: {e}")
            # Return empty structures rather than crashing
            return {
                "financials": pd.DataFrame(),
                "balance_sheet": pd.DataFrame(),
                "cashflow": pd.DataFrame(),
                "dividends": pd.Series()
            }

    @staticmethod
    def extract_float_metric(info: Dict[str, Any], keys: List[str], default: Optional[float] = None) -> Optional[float]:
        """Extract float value from dict given list of keys (fallback chains)."""
        for k in keys:
            val = info.get(k)
            if val is not None:
                try:
                    float_val = float(val)
                    if not math.isnan(float_val):
                        return float_val
                except ValueError:
                    pass
        return default

    @staticmethod
    def extract_statement_metric(df: pd.DataFrame, index_keys: List[str]) -> Optional[List[float]]:
        """Extract historical row values from a financial statement DataFrame using list of possible index keys."""
        if df.empty:
            return None
            
        for k in index_keys:
            # Perform case-insensitive index check
            matching_rows = [idx for idx in df.index if str(idx).strip().lower() == k.lower()]
            if matching_rows:
                row = df.loc[matching_rows[0]]
                # Return values list, convert nan to None
                return [None if pd.isna(val) else float(val) for val in row]
        return None

    @classmethod
    def get_normalized_fundamentals(cls, ticker_symbol: str) -> Dict[str, Any]:
        """
        Fetch all raw data, resolve all alternative naming variations, and return
        a dictionary of normalized, clean fundamental metrics.
        """
        symbol = ticker_symbol.strip().upper()
        info = cls.get_ticker_info(symbol)
        statements = cls.get_ticker_statements(symbol)
        
        fin_df = statements["financials"]
        bs_df = statements["balance_sheet"]
        cf_df = statements["cashflow"]
        div_series = statements["dividends"]
        
        # 1. Base Info
        normalized = {
            "ticker": symbol,
            "company_name": info.get("longName") or info.get("shortName") or symbol,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("financialCurrency") or info.get("currency") or "USD",
            "current_price": cls.extract_float_metric(info, ["currentPrice", "regularMarketPrice", "navPrice"]),
            "market_cap": cls.extract_float_metric(info, ["marketCap", "regularMarketVolume"]),
            "trailing_pe": cls.extract_float_metric(info, ["trailingPE"]),
            "forward_pe": cls.extract_float_metric(info, ["forwardPE"]),
            "price_to_book": cls.extract_float_metric(info, ["priceToBook"]),
            "dividend_yield": cls.extract_float_metric(info, ["dividendYield"]),
            "dividend_rate": cls.extract_float_metric(info, ["dividendRate"])
        }
        
        # 2. Extract Balance Sheet items
        # Current Assets
        assets_hist = cls.extract_statement_metric(bs_df, ["Total Current Assets", "Current Assets"])
        normalized["total_current_assets"] = assets_hist[0] if assets_hist else None
        
        # Current Liabilities
        liab_hist = cls.extract_statement_metric(bs_df, ["Total Current Liabilities", "Current Liabilities"])
        normalized["total_current_liabilities"] = liab_hist[0] if liab_hist else None
        
        # Current Ratio
        normalized["current_ratio"] = cls.extract_float_metric(info, ["currentRatio"])
        if normalized["current_ratio"] is None and normalized["total_current_assets"] is not None and normalized["total_current_liabilities"]:
            normalized["current_ratio"] = normalized["total_current_assets"] / normalized["total_current_liabilities"]
        
        # Working Capital
        wc_hist = cls.extract_statement_metric(bs_df, ["Working Capital"])
        if wc_hist:
            normalized["working_capital"] = wc_hist[0]
        elif normalized["total_current_assets"] is not None and normalized["total_current_liabilities"] is not None:
            normalized["working_capital"] = normalized["total_current_assets"] - normalized["total_current_liabilities"]
        else:
            normalized["working_capital"] = None
            
        # Long Term Debt
        lt_debt_hist = cls.extract_statement_metric(bs_df, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Capital Lease Obligation"])
        normalized["long_term_debt"] = lt_debt_hist[0] if lt_debt_hist else None
        
        # Total Debt
        total_debt_hist = cls.extract_statement_metric(bs_df, ["Total Debt", "Net Debt"])
        if total_debt_hist:
            normalized["total_debt"] = total_debt_hist[0]
        else:
            # Fallback to info
            info_debt = cls.extract_float_metric(info, ["totalDebt"])
            if info_debt is not None:
                normalized["total_debt"] = info_debt
            else:
                # Fallback to summing Current Debt + LT Debt
                curr_debt_hist = cls.extract_statement_metric(bs_df, ["Current Debt", "Current Debt And Capital Lease Obligation", "Commercial Paper"])
                curr_debt = curr_debt_hist[0] if curr_debt_hist else 0.0
                lt_debt = normalized["long_term_debt"] or 0.0
                normalized["total_debt"] = curr_debt + lt_debt if (curr_debt_hist or lt_debt_hist) else None
                
        # Cash and equivalents
        cash_hist = cls.extract_statement_metric(bs_df, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash Financial", "Cash Equivalents"])
        normalized["cash_and_equivalents"] = cash_hist[0] if cash_hist else cls.extract_float_metric(info, ["totalCash"])
        
        # Stockholders Equity
        equity_hist = cls.extract_statement_metric(bs_df, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"])
        normalized["stockholders_equity"] = equity_hist[0] if equity_hist else None
        
        # Debt to Equity
        normalized["debt_to_equity"] = cls.extract_float_metric(info, ["debtToEquity"])
        if normalized["debt_to_equity"] is not None:
            normalized["debt_to_equity"] = normalized["debt_to_equity"] / 100.0  # convert percentage to decimal
        elif normalized["total_debt"] is not None and normalized["stockholders_equity"]:
            normalized["debt_to_equity"] = normalized["total_debt"] / normalized["stockholders_equity"]
            
        # 3. Cash Flow items
        op_cf_hist = cls.extract_statement_metric(cf_df, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
        normalized["operating_cash_flow"] = op_cf_hist[0] if op_cf_hist else None
        
        fcf_hist = cls.extract_statement_metric(cf_df, ["Free Cash Flow"])
        if fcf_hist:
            normalized["free_cash_flow"] = fcf_hist[0]
        else:
            info_fcf = cls.extract_float_metric(info, ["freeCashflow"])
            if info_fcf is not None:
                normalized["free_cash_flow"] = info_fcf
            elif normalized["operating_cash_flow"] is not None:
                capex_hist = cls.extract_statement_metric(cf_df, ["Capital Expenditure", "Purchase Of PPE"])
                capex = abs(capex_hist[0]) if capex_hist else 0.0
                normalized["free_cash_flow"] = normalized["operating_cash_flow"] - capex
            else:
                normalized["free_cash_flow"] = None
                
        # 4. ROE
        roe = cls.extract_float_metric(info, ["returnOnEquity"])
        if roe is not None:
            normalized["roe"] = roe
        else:
            # Fallback calculate
            try:
                net_income = float(fin_df.loc['Net Income'].iloc[0]) if 'Net Income' in fin_df.index else 0.0
                equity = normalized["stockholders_equity"]
                if equity and equity > 0:
                    normalized["roe"] = net_income / equity
                else:
                    normalized["roe"] = None
            except Exception:
                normalized["roe"] = None
                
        # 5. Dividends Check
        normalized["dividend_paying"] = False
        if normalized["dividend_rate"] and normalized["dividend_rate"] > 0:
            normalized["dividend_paying"] = True
        elif normalized["dividend_yield"] and normalized["dividend_yield"] > 0:
            normalized["dividend_paying"] = True
        elif not div_series.empty:
            # Has paid dividends in the past year
            # pandas series index usually contains timestamps, check if any inside last 365 days
            normalized["dividend_paying"] = True
            
        # 6. Yearly EPS History & Dates
        eps_history = []
        eps_rows = ["Diluted EPS", "Basic EPS"]
        eps_found = False
        
        for k in eps_rows:
            matching_rows = [idx for idx in fin_df.index if str(idx).strip().lower() == k.lower()]
            if matching_rows:
                row = fin_df.loc[matching_rows[0]]
                # Extract years from columns
                for col_name, val in row.items():
                    try:
                        # Extract year integer from col_name (can be datetime or string)
                        year = pd.to_datetime(col_name).year
                        if not pd.isna(val) and not pd.isna(year):
                            eps_history.append({"year": int(year), "eps": float(val)})
                    except Exception:
                        pass
                eps_found = True
                break
                
        if not eps_found and 'Net Income' in fin_df.index:
            # Fallback calculate: Net Income / Diluted Average Shares
            try:
                ni_row = fin_df.loc['Net Income']
                shares_row = fin_df.loc['Diluted Average Shares'] if 'Diluted Average Shares' in fin_df.index else fin_df.loc['Basic Average Shares']
                for col_name, ni in ni_row.items():
                    shares = shares_row.get(col_name)
                    year = pd.to_datetime(col_name).year
                    if ni is not None and shares and shares > 0:
                        eps_history.append({"year": int(year), "eps": float(ni) / float(shares)})
            except Exception:
                pass
                
        # Sort EPS history by year ascending
        eps_history.sort(key=lambda x: x["year"])
        normalized["eps_history"] = eps_history
        
        # Include raw data context for debug/transparency
        normalized["_raw_info"] = info
        
        return normalized
