import logging
import math
import asyncio
import io
import requests
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
from cachetools import TTLCache
from app.schemas.bagger import (
    BaggerFilterConfig,
    StockMetrics,
    ScreenerCheckResult,
    BaggerCandidate,
    YearlyMetric
)
from app.services.yahoo_client import YahooFinanceClient, get_yf_ticker
from bs4 import BeautifulSoup

logger = logging.getLogger("tradeservices.bagger_scanner")

def sanitize_for_json(val: Any) -> Any:
    """
    Recursively sanitize dictionaries, lists, and floats to ensure they are
    fully JSON-compliant (i.e. converting Infinity, -Infinity, and NaN to None/null).
    """
    if isinstance(val, dict):
        return {k: sanitize_for_json(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_for_json(v) for v in val]
    elif isinstance(val, float):
        if math.isinf(val) or math.isnan(val):
            return None
        return val
    return val

# Cache for NSE symbol list (24 hours TTL)
nse_symbols_cache = TTLCache(maxsize=1, ttl=86400)
# Cache for US symbol list (24 hours TTL)
us_symbols_cache = TTLCache(maxsize=1, ttl=86400)

class BaggerScannerService:
    @staticmethod
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
            df.columns = [c.strip() for c in df.columns]
            
            # Filter for Series == 'EQ' (Common equities)
            eq_df = df[df["SERIES"].str.strip().str.upper() == "EQ"]
            symbols = sorted(eq_df["SYMBOL"].str.strip().tolist())
            
            if symbols:
                nse_symbols_cache["symbols"] = symbols
                return symbols
        except Exception as e:
            logger.error(f"Failed to download/parse NSE equity register: {e}")
            
        # Fallback list if the live download fails (ensures app is resilient)
        fallback = ["3MINDIA", "ABB", "ACC", "ADANIENT", "ADANIPORTS", "AMBUJACEM", "APOLLOHOSP", "ASIANPAINT", "ASTRAL"]
        return fallback

    @staticmethod
    def fetch_us_symbols() -> List[str]:
        """
        Download and parse the US stock symbol registry.
        """
        if "symbols" in us_symbols_cache:
            return us_symbols_cache["symbols"]
            
        nasdaq_url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt"
        nyse_url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_tickers.txt"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        logger.info("Downloading active equities registers from public US Nasdaq & NYSE symbol registries...")
        symbols_set = set()
        try:
            # Download Nasdaq tickers
            res_nasdaq = requests.get(nasdaq_url, headers=headers, timeout=15)
            if res_nasdaq.status_code == 200:
                for line in res_nasdaq.text.splitlines():
                    sym = line.strip().upper()
                    if sym.isalpha() and len(sym) <= 5:
                        symbols_set.add(sym)
            
            # Download NYSE tickers
            res_nyse = requests.get(nyse_url, headers=headers, timeout=15)
            if res_nyse.status_code == 200:
                for line in res_nyse.text.splitlines():
                    sym = line.strip().upper()
                    if sym.isalpha() and len(sym) <= 5:
                        symbols_set.add(sym)
                        
            symbols = sorted(list(symbols_set))
            if symbols:
                us_symbols_cache["symbols"] = symbols
                return symbols
        except Exception as e:
            logger.error(f"Failed to download/parse US stock symbol registry: {e}")
            
        # Fallback to liquid S&P stocks
        fallback = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "LLY", "UNH", "V", "JPM", "AVGO", "XOM"]
        return fallback

    @staticmethod
    def _calculate_cagr(history: List[YearlyMetric]) -> Optional[float]:
        """Calculate compound annual growth rate (%) over available history."""
        if len(history) < 2:
            return None
        sorted_history = sorted(history, key=lambda x: x.year)
        start = sorted_history[0]
        end = sorted_history[-1]
        
        years = end.year - start.year
        if years <= 0 or start.value <= 0 or end.value <= 0:
            return None
            
        try:
            cagr = ((end.value / start.value) ** (1.0 / years) - 1.0) * 100.0
            return round(cagr, 2)
        except Exception:
            return None

    @classmethod
    def scrape_screener_in(cls, symbol: str) -> Dict[str, Any]:
        """
        Scrape Screener.in consolidated page for an Indian stock ticker.
        Returns parsed fundamentals dictionary of metrics.
        """
        # Clean ticker (e.g. DELHIVERY.NS -> DELHIVERY)
        clean_symbol = symbol.split(".")[0].upper()
        url = f"https://www.screener.in/company/{clean_symbol}/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        data = {}
        try:
            logger.info(f"Scraping Screener.in Consolidated view for {clean_symbol}...")
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                logger.warning(f"Screener.in returned status code {res.status_code} for {clean_symbol}")
                return data
                
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 0. Parse company name header
            company_header = soup.find("h1")
            if company_header:
                data["company_name"] = company_header.text.strip()
                
            # 1. Parse top ratios cards
            ratio_items = soup.find_all("li", class_="flex")
            for li in ratio_items:
                text = li.text.strip().replace("\n", "")
                normalized_text = " ".join(text.split())
                if "Market Cap" in normalized_text:
                    try:
                        val_str = normalized_text.split("₹")[-1].split("Cr.")[0].strip().replace(",", "")
                        data["market_cap"] = float(val_str) * 1e7 # convert Crore to absolute INR
                    except Exception:
                        pass
                elif "Current Price" in normalized_text:
                    try:
                        val_str = normalized_text.split("₹")[-1].strip().replace(",", "")
                        data["current_price"] = float(val_str)
                    except Exception:
                        pass
                elif "Stock P/E" in normalized_text:
                    try:
                        val_str = normalized_text.split("Stock P/E")[-1].strip().replace(",", "")
                        data["trailing_pe"] = float(val_str)
                    except Exception:
                        pass
                elif "Book Value" in normalized_text:
                    try:
                        val_str = normalized_text.split("₹")[-1].strip().replace(",", "")
                        data["book_value"] = float(val_str)
                    except Exception:
                        pass
                elif "ROE" in normalized_text:
                    try:
                        val_str = normalized_text.split("ROE")[-1].split("%")[0].strip().replace(",", "")
                        data["roe"] = float(val_str)
                    except Exception:
                        pass
                        
            # 2. Parse P&L Table (Revenue, EPS)
            pl_section = soup.find("section", id="profit-loss")
            if pl_section:
                header_row = pl_section.find("tr")
                years = []
                if header_row:
                    for th in header_row.find_all("th")[1:]:
                        text = th.text.strip()
                        try:
                            year = int(text.split()[-1])
                            years.append(year)
                        except Exception:
                            years.append(None)
                            
                for row in pl_section.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    row_label = cells[0].text.strip().lower()
                    
                    if "sales" in row_label:
                        rev_history = []
                        for yr, td in zip(years, cells[1:]):
                            val_str = td.text.strip().replace(",", "")
                            try:
                                val = float(val_str) * 1e7
                                if yr is not None and val > 0:
                                    rev_history.append({"year": yr, "value": val})
                            except Exception:
                                pass
                        data["revenue_history"] = rev_history
                    elif "eps" in row_label:
                        eps_history = []
                        for yr, td in zip(years, cells[1:]):
                            val_str = td.text.strip().replace(",", "")
                            try:
                                val = float(val_str)
                                if yr is not None:
                                    eps_history.append({"year": yr, "value": val})
                            except Exception:
                                pass
                        data["eps_history"] = eps_history
                    elif "net profit" in row_label:
                        net_profit_history = []
                        for yr, td in zip(years, cells[1:]):
                            val_str = td.text.strip().replace(",", "")
                            try:
                                val = float(val_str)
                                if yr is not None:
                                    net_profit_history.append({"year": yr, "value": val})
                            except Exception:
                                pass
                        data["net_profit_history"] = net_profit_history
                        
            # 3. Parse Balance Sheet Table (Debt, Reserves, Capital)
            bs_section = soup.find("section", id="balance-sheet")
            if bs_section:
                borrowings_list = []
                reserves_list = []
                equity_capital_list = []
                
                for row in bs_section.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    row_label = cells[0].text.strip().lower()
                    
                    if "borrowings" in row_label:
                        for td in cells[1:]:
                            val_str = td.text.strip().replace(",", "")
                            try:
                                borrowings_list.append(float(val_str) * 1e7)
                            except Exception:
                                borrowings_list.append(0.0)
                    elif "reserves" in row_label:
                        for td in cells[1:]:
                            val_str = td.text.strip().replace(",", "")
                            try:
                                reserves_list.append(float(val_str) * 1e7)
                            except Exception:
                                reserves_list.append(0.0)
                    elif "equity capital" in row_label or "share capital" in row_label:
                        for td in cells[1:]:
                            val_str = td.text.strip().replace(",", "")
                            try:
                                equity_capital_list.append(float(val_str) * 1e7)
                            except Exception:
                                equity_capital_list.append(0.0)
                                
                if borrowings_list and (reserves_list or equity_capital_list):
                    latest_borrowings = borrowings_list[-1]
                    latest_equity = 0.0
                    if reserves_list:
                        latest_equity += reserves_list[-1]
                    if equity_capital_list:
                        latest_equity += equity_capital_list[-1]
                    if latest_equity > 0:
                        data["debt_to_equity"] = latest_borrowings / latest_equity
                        
            # 4. Parse Shareholding Pattern Table (Promoter Holding)
            sh_section = soup.find("section", id="shareholding")
            if sh_section:
                for row in sh_section.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    row_label = cells[0].text.strip().lower()
                    if "promoter" in row_label or "promoters" in row_label:
                        try:
                            latest_holding_str = cells[-1].text.strip().replace("%", "")
                            data["promoter_holding"] = float(latest_holding_str)
                        except Exception:
                            pass
                            
            # 5. Parse Cash Flow Table (Cash from Operating Activity)
            cf_section = soup.find("section", id="cash-flow")
            if cf_section:
                cf_years = []
                cf_header = cf_section.find("tr")
                if cf_header:
                    for th in cf_header.find_all("th")[1:]:
                        text = th.text.strip()
                        try:
                            cf_years.append(int(text.split()[-1]))
                        except Exception:
                            cf_years.append(None)
                            
                for row in cf_section.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    row_label = cells[0].text.strip().lower()
                    if "cash from operating activity" in row_label or "operating activity" in row_label:
                        ocf_history = []
                        for yr, td in zip(cf_years, cells[1:]):
                            val_str = td.text.strip().replace(",", "")
                            try:
                                is_neg = False
                                if val_str.startswith("(") and val_str.endswith(")"):
                                    val_str = val_str[1:-1]
                                    is_neg = True
                                val = float(val_str)
                                if yr is not None:
                                    ocf_history.append({"year": yr, "value": -val if is_neg else val})
                            except Exception:
                                pass
                        data["ocf_history"] = ocf_history
                        
            # 6. Compute Cash Flow Quality ratio from Screener P&L and Cash Flow
            if "ocf_history" in data and "net_profit_history" in data:
                ratios = []
                ocf_dict = {item["year"]: item["value"] for item in data["ocf_history"]}
                for item in data["net_profit_history"]:
                    yr = item["year"]
                    np_val = item["value"]
                    if yr in ocf_dict and np_val and np_val > 0:
                        ratios.append(ocf_dict[yr] / np_val)
                if ratios:
                    data["ocf_to_net_income_ratio"] = sum(ratios) / len(ratios)
        except Exception as e:
            logger.error(f"Error scraping Screener.in for {clean_symbol}: {e}")
            
        return data

    @classmethod
    def get_stock_metrics(cls, symbol: str) -> StockMetrics:
        """Fetch and normalize financial metrics for a symbol using YahooFinanceClient."""
        yf_symbol = symbol.strip().upper()
        if not yf_symbol.endswith(".NS") and not yf_symbol.endswith(".BO") and "^" not in yf_symbol:
            try:
                nse_list = cls.fetch_nse_symbols()
                base_sym = yf_symbol.replace(".NS", "").replace(".BO", "")
                if base_sym in nse_list:
                    yf_symbol = f"{base_sym}.NS"
            except Exception:
                # Fallback to appending .NS if registry fetch fails
                yf_symbol = f"{yf_symbol}.NS"
            
        # Query unified client (includes fast_info caching/retries)
        info = YahooFinanceClient.get_ticker_info(yf_symbol)
        statements = YahooFinanceClient.get_ticker_statements(yf_symbol)
        
        fin_df = statements["financials"]
        bs_df = statements["balance_sheet"]
        
        # 1. Base Info
        current_price = YahooFinanceClient.extract_float_metric(info, ["currentPrice", "regularMarketPrice", "navPrice"])
        market_cap = YahooFinanceClient.extract_float_metric(info, ["marketCap", "regularMarketVolume"])
        trailing_pe = YahooFinanceClient.extract_float_metric(info, ["trailingPE"])
        forward_pe = YahooFinanceClient.extract_float_metric(info, ["forwardPE"])
        roe = YahooFinanceClient.extract_float_metric(info, ["returnOnEquity"])
        op_margin = YahooFinanceClient.extract_float_metric(info, ["operatingMargins"])
        
        if roe is not None:
            roe = roe * 100.0
        if op_margin is not None:
            op_margin = op_margin * 100.0
            
        company_name = info.get("longName") or info.get("shortName") or symbol
            
        # Debt to Equity
        debt_to_equity = YahooFinanceClient.extract_float_metric(info, ["debtToEquity"])
        if debt_to_equity is not None:
            debt_to_equity = debt_to_equity / 100.0
        else:
            try:
                total_debt_list = YahooFinanceClient.extract_statement_metric(bs_df, ["Total Debt", "Net Debt"])
                equity_list = YahooFinanceClient.extract_statement_metric(bs_df, ["Stockholders Equity", "Common Stock Equity"])
                if total_debt_list and equity_list and equity_list[0] and equity_list[0] > 0:
                    debt_to_equity = total_debt_list[0] / equity_list[0]
            except Exception:
                pass

        # Promoter Holding & Pledging
        promoter_holding = YahooFinanceClient.extract_float_metric(info, ["heldPercentInsiders", "insiderOwnersPercent"])
        if promoter_holding is not None:
            promoter_holding = promoter_holding * 100.0
            
        pledged_percentage = YahooFinanceClient.extract_float_metric(info, ["pledgedPercentInsiders"])
        if pledged_percentage is not None:
            pledged_percentage = pledged_percentage * 100.0
        else:
            pledged_percentage = 0.0
            
        # Cash Flow Quality
        cf_df = statements["cashflow"]
        ocf_to_net_income_ratio = None
        
        ocf_rows = ["Operating Cash Flow", "Cash Flow From Operating Activities", "Total Cash From Operating Activities", "Net Cash Provided By Operating Activities"]
        ocf_vals = YahooFinanceClient.extract_statement_metric(cf_df, ocf_rows)
        
        net_income_rows = ["Net Income", "Net Income From Continuing Operations", "Net Income Common Stockholders"]
        net_income_vals = YahooFinanceClient.extract_statement_metric(fin_df, net_income_rows)
        
        if ocf_vals and net_income_vals:
            ratios = []
            for ocf, ni in zip(ocf_vals, net_income_vals):
                if ni and ni > 0 and ocf is not None:
                    ratios.append(ocf / ni)
            if ratios:
                ocf_to_net_income_ratio = sum(ratios) / len(ratios)
                
        # 2. Revenue & EPS History
        revenue_history = []
        eps_history = []
        
        rev_rows = ["Total Revenue", "Operating Revenue", "Revenue"]
        rev_vals = YahooFinanceClient.extract_statement_metric(fin_df, rev_rows)
        if rev_vals:
            years = []
            for col in fin_df.columns:
                try:
                    years.append(pd.to_datetime(col).year)
                except Exception:
                    years.append(None)
            for yr, val in zip(years, rev_vals):
                if yr is not None and val is not None and val > 0:
                    revenue_history.append(YearlyMetric(year=int(yr), value=float(val)))
                    
        eps_rows = ["Diluted EPS", "Basic EPS"]
        eps_vals = YahooFinanceClient.extract_statement_metric(fin_df, eps_rows)
        if eps_vals:
            years = []
            for col in fin_df.columns:
                try:
                    years.append(pd.to_datetime(col).year)
                except Exception:
                    years.append(None)
            for yr, val in zip(years, eps_vals):
                if yr is not None and val is not None:
                    eps_history.append(YearlyMetric(year=int(yr), value=float(val)))
                    
        # Check if we should scrape Screener.in as a secondary source fallback for Indian stocks
        is_indian_stock = yf_symbol.endswith(".NS") or yf_symbol.endswith(".BO")
        if is_indian_stock and (not revenue_history or market_cap is None or roe is None or promoter_holding is None or debt_to_equity is None or ocf_to_net_income_ratio is None):
            logger.info(f"Yfinance data incomplete for Indian stock {yf_symbol}; querying Screener.in fallback...")
            screener_data = cls.scrape_screener_in(yf_symbol)
            if screener_data:
                if "company_name" in screener_data and (company_name == symbol or company_name == yf_symbol):
                    company_name = screener_data["company_name"]
                if market_cap is None and "market_cap" in screener_data:
                    market_cap = screener_data["market_cap"]
                if current_price is None and "current_price" in screener_data:
                    current_price = screener_data["current_price"]
                if trailing_pe is None and "trailing_pe" in screener_data:
                    trailing_pe = screener_data["trailing_pe"]
                if roe is None and "roe" in screener_data:
                    roe = screener_data["roe"]
                if promoter_holding is None and "promoter_holding" in screener_data:
                    promoter_holding = screener_data["promoter_holding"]
                if debt_to_equity is None and "debt_to_equity" in screener_data:
                    debt_to_equity = screener_data["debt_to_equity"]
                if ocf_to_net_income_ratio is None and "ocf_to_net_income_ratio" in screener_data:
                    ocf_to_net_income_ratio = screener_data["ocf_to_net_income_ratio"]
                if not revenue_history and "revenue_history" in screener_data:
                    for item in screener_data["revenue_history"]:
                        revenue_history.append(YearlyMetric(year=item["year"], value=item["value"]))
                if not eps_history and "eps_history" in screener_data:
                    for item in screener_data["eps_history"]:
                        eps_history.append(YearlyMetric(year=item["year"], value=item["value"]))
                        
        # 3. Calculate ROIC History
        roic_history = []
        raw_roic = YahooFinanceClient.calculate_roic_history(fin_df, bs_df)
        if raw_roic:
            for item in raw_roic:
                roic_history.append(YearlyMetric(year=item["year"], value=item["roic"]))
                
        # EBITDA
        ebitda_history = []
        ebitda_vals = YahooFinanceClient.extract_statement_metric(fin_df, ["EBITDA"])
        if not ebitda_vals:
            # Fallback to Operating Income + Depreciation & Amortization
            op_inc_vals = YahooFinanceClient.extract_statement_metric(fin_df, ["Operating Income", "EBIT"])
            cf_df = statements.get("cashflow") if isinstance(statements, dict) else pd.DataFrame()
            da_vals = YahooFinanceClient.extract_statement_metric(cf_df if cf_df is not None else pd.DataFrame(), ["Depreciation And Amortization", "Depreciation & Amortization", "Depreciation", "Amortization"])
            if op_inc_vals:
                ebitda_vals = []
                for idx, op_inc in enumerate(op_inc_vals):
                    da = abs(da_vals[idx]) if (da_vals and idx < len(da_vals) and da_vals[idx] is not None) else 0.0
                    ebitda_vals.append(op_inc + da if op_inc is not None else None)
                    
        if ebitda_vals:
            years = []
            for col in fin_df.columns:
                try:
                    years.append(pd.to_datetime(col).year)
                except Exception:
                    years.append(None)
            for yr, val in zip(years, ebitda_vals):
                if yr is not None and val is not None:
                    ebitda_history.append(YearlyMetric(year=int(yr), value=float(val)))
                    
        # Receivables
        receivables_history = []
        rec_vals = YahooFinanceClient.extract_statement_metric(bs_df, ["Accounts Receivable", "Receivables", "Net Receivables"])
        if rec_vals:
            years = []
            for col in bs_df.columns:
                try:
                    years.append(pd.to_datetime(col).year)
                except Exception:
                    years.append(None)
            for yr, val in zip(years, rec_vals):
                if yr is not None and val is not None:
                    receivables_history.append(YearlyMetric(year=int(yr), value=float(val)))
        # Average Traded Volume
        average_volume = YahooFinanceClient.extract_float_metric(info, ["averageVolume", "averageVolume10days", "volume"])
        
        # CFO / EBITDA 3y average
        cfo_to_ebitda_avg = None
        cfo_vals = YahooFinanceClient.extract_statement_metric(cf_df if cf_df is not None else pd.DataFrame(), ["Operating Cash Flow", "Cash Flow From Operating Activities", "Total Cash From Operating Activities"])
        if ebitda_vals and cfo_vals:
            ratios = []
            for e_val, c_val in zip(ebitda_vals, cfo_vals):
                if e_val and c_val and e_val > 0:
                    ratios.append(c_val / e_val)
            if ratios:
                cfo_to_ebitda_avg = sum(ratios) / len(ratios)
                        
        return StockMetrics(
            ticker=yf_symbol,
            company_name=company_name,
            currency=info.get("currency") or "INR",
            market_cap=market_cap,
            current_price=current_price,
            trailing_pe=trailing_pe,
            forward_pe=forward_pe,
            roe=roe,
            operating_margin=op_margin,
            debt_to_equity=debt_to_equity,
            promoter_holding=promoter_holding,
            ocf_to_net_income_ratio=ocf_to_net_income_ratio,
            pledged_percentage=pledged_percentage,
            revenue_history=revenue_history,
            eps_history=eps_history,
            roic_history=roic_history,
            ebitda_history=ebitda_history,
            receivables_history=receivables_history,
            average_volume=average_volume,
            cfo_to_ebitda_avg=cfo_to_ebitda_avg
        )

    @classmethod
    def evaluate_candidate(cls, metrics: StockMetrics, config: BaggerFilterConfig) -> BaggerCandidate:
        """Run all 100-bagger checks on normalized metrics."""
        checks = []
        missing_fields = []
        warnings = []
        
        achieved_weight = 0.0
        possible_weight = 0.0
        evaluable_checks = 0
        passed_checks = 0
        
        # 1. Starting Size Check (Weight 20)
        mcap = metrics.market_cap
        if mcap is not None:
            possible_weight += 20.0
            evaluable_checks += 1
            is_us_stock = not (metrics.ticker.endswith(".NS") or metrics.ticker.endswith(".BO"))
            if is_us_stock:
                passed = mcap <= config.max_market_cap_usd
                desc = f"Market Cap: ${mcap/1e6:.2f}M USD " + ("<=" if passed else ">") + f" ${config.max_market_cap_usd/1e6:.1f}M USD"
            else:
                passed = mcap <= config.max_market_cap_inr
                desc = f"Market Cap: {mcap/1e7:.2f} Cr INR " + ("<=" if passed else ">") + f" {config.max_market_cap_inr/1e7:.1f} Cr INR"
            if passed:
                achieved_weight += 20.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Starting Size", passed=passed, description=desc, weight=20.0, achieved_weight=20.0 if passed else 0.0))
        else:
            missing_fields.append("marketCap")
            warnings.append("Market cap unavailable; size check skipped.")
            
        # 2. Sales Growth CAGR Check (Weight 15)
        rev_cagr = cls._calculate_cagr(metrics.revenue_history)
        if rev_cagr is not None:
            possible_weight += 15.0
            evaluable_checks += 1
            passed = rev_cagr >= config.min_revenue_cagr
            desc = f"Sales CAGR: {rev_cagr:.2f}% " + (">=" if passed else "<") + f" {config.min_revenue_cagr:.1f}%"
            if passed:
                achieved_weight += 15.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Sales Growth (CAGR)", passed=passed, description=desc, weight=15.0, achieved_weight=15.0 if passed else 0.0))
        else:
            missing_fields.append("revenueHistory")
            warnings.append("Revenue history insufficient to calculate CAGR; growth check skipped.")
            
        # 3. EPS Growth CAGR Check (Weight 10)
        eps_cagr = cls._calculate_cagr(metrics.eps_history)
        if eps_cagr is not None:
            possible_weight += 10.0
            evaluable_checks += 1
            passed = eps_cagr >= config.min_earnings_cagr
            desc = f"EPS CAGR: {eps_cagr:.2f}% " + (">=" if passed else "<") + f" {config.min_earnings_cagr:.1f}%"
            if passed:
                achieved_weight += 10.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="EPS Growth (CAGR)", passed=passed, description=desc, weight=10.0, achieved_weight=10.0 if passed else 0.0))
        else:
            missing_fields.append("epsHistory")
            warnings.append("EPS history insufficient to calculate CAGR; EPS growth check skipped.")
            
        # 4. Capital Return Efficiency Check (Weight 20)
        roe_val = metrics.roe
        if roe_val is not None:
            possible_weight += 20.0
            evaluable_checks += 1
            passed = roe_val >= config.min_roe
            desc = f"Return on Equity: {roe_val:.2f}% " + (">=" if passed else "<") + f" {config.min_roe:.1f}%"
            if passed:
                achieved_weight += 20.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Capital Efficiency (ROE)", passed=passed, description=desc, weight=20.0, achieved_weight=20.0 if passed else 0.0))
        else:
            missing_fields.append("returnOnEquity")
            warnings.append("ROE metadata unavailable; efficiency check skipped.")
            
        # 5. Operating Moat Margin Check (Weight 15)
        margin = metrics.operating_margin
        if margin is not None:
            possible_weight += 15.0
            evaluable_checks += 1
            passed = margin >= config.min_operating_margin
            desc = f"Operating Margin: {margin:.2f}% " + (">=" if passed else "<") + f" {config.min_operating_margin:.1f}%"
            if passed:
                achieved_weight += 15.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Operating Moat (Margins)", passed=passed, description=desc, weight=15.0, achieved_weight=15.0 if passed else 0.0))
        else:
            missing_fields.append("operatingMargins")
            warnings.append("Operating margin metadata unavailable; moat check skipped.")
            
        # 6. Reasonable Valuation Check (Weight 5)
        pe = metrics.trailing_pe
        if pe is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            passed = 0.0 < pe <= config.max_pe_ratio
            desc = f"Trailing PE: {pe:.2f} " + ("<=" if passed else ">") + f" {config.max_pe_ratio:.1f}"
            if passed:
                achieved_weight += 5.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Reasonable PE Ratio", passed=passed, description=desc, weight=5.0, achieved_weight=5.0 if passed else 0.0))
        else:
            missing_fields.append("trailingPE")
            warnings.append("PE ratio metadata unavailable; valuation check skipped.")
            
        # 7. Promoter Ownership Check (Weight 5)
        holding = metrics.promoter_holding
        if holding is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            passed = holding >= config.min_promoter_holding
            desc = f"Promoter Holding: {holding:.2f}% " + (">=" if passed else "<") + f" {config.min_promoter_holding:.1f}%"
            if passed:
                achieved_weight += 5.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Promoter Holding", passed=passed, description=desc, weight=5.0, achieved_weight=5.0 if passed else 0.0))
        else:
            missing_fields.append("promoterHolding")
            warnings.append("Promoter/Insider holding metadata unavailable; promoter holding check skipped.")
            
        # 8. Debt Safety Check (Weight 10)
        de = metrics.debt_to_equity
        if de is not None:
            possible_weight += 10.0
            evaluable_checks += 1
            passed = de <= config.max_debt_to_equity
            desc = f"Debt-to-Equity: {de:.2f} " + ("<=" if passed else ">") + f" {config.max_debt_to_equity:.1f}"
            if passed:
                achieved_weight += 10.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Debt Safety", passed=passed, description=desc, weight=10.0, achieved_weight=10.0 if passed else 0.0))
        else:
            missing_fields.append("debtToEquity")
            warnings.append("Debt-to-Equity metadata unavailable; safety check skipped.")
            
        # 9. Cash Flow Quality Check (Weight 10)
        cf_ratio = metrics.ocf_to_net_income_ratio
        if cf_ratio is not None:
            possible_weight += 10.0
            evaluable_checks += 1
            passed = cf_ratio >= config.min_ocf_to_net_income_ratio
            desc = f"OCF/Net Income Ratio: {cf_ratio:.2f} " + (">=" if passed else "<") + f" {config.min_ocf_to_net_income_ratio:.2f}"
            if passed:
                achieved_weight += 10.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Cash Flow Quality", passed=passed, description=desc, weight=10.0, achieved_weight=10.0 if passed else 0.0))
        else:
            missing_fields.append("ocfToNetIncomeRatio")
            warnings.append("Operating Cash Flow or Net Income history insufficient; cash flow quality check skipped.")
            
        # 10. Promoter Pledged Shares Check (Weight 5)
        pledged = metrics.pledged_percentage
        if pledged is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            passed = pledged <= config.max_pledged_percentage
            desc = f"Pledged Shares: {pledged:.2f}% " + ("<=" if passed else ">") + f" {config.max_pledged_percentage:.2f}%"
            if passed:
                achieved_weight += 5.0
                passed_checks += 1
            checks.append(ScreenerCheckResult(check_name="Promoter Pledging", passed=passed, description=desc, weight=5.0, achieved_weight=5.0 if passed else 0.0))
        else:
            missing_fields.append("pledgedPercentage")
            warnings.append("Promoter pledging data unavailable; pledging check skipped.")

        # Final calculations
        score = (achieved_weight / possible_weight) * 100.0 if possible_weight > 0 else 0.0
        pass_ratio = passed_checks / evaluable_checks if evaluable_checks > 0 else 0.0
        
        # Classification Mapping
        if possible_weight < 50.0:
            label = "Insufficient Data"
        elif score >= 90.0 and pass_ratio >= config.min_pass_ratio:
            label = "High Potential"
        elif 60.0 <= score < 80.0:
            label = "Moderate Potential"
        else:
            label = "Low Potential"
            
        passed = (label == "High Potential")
        
        metrics_dict = {
            "market_cap": metrics.market_cap,
            "current_price": metrics.current_price,
            "trailing_pe": metrics.trailing_pe,
            "forward_pe": metrics.forward_pe,
            "roe": metrics.roe,
            "operating_margin": metrics.operating_margin,
            "debt_to_equity": metrics.debt_to_equity,
            "promoter_holding": metrics.promoter_holding,
            "ocf_to_net_income_ratio": cf_ratio,
            "pledged_percentage": pledged,
            "revenue_cagr": rev_cagr,
            "eps_cagr": eps_cagr
        }
        
        symbol = metrics.ticker.split(".")[0]
        explanation = (
            f"{metrics.company_name or symbol} ({metrics.ticker}) evaluated on {passed_checks}/{evaluable_checks} "
            f"checks, achieving a 100-bagger potential score of {score:.1f}%."
        )
        if passed:
            explanation += " This stock strongly aligns with Christopher Mayer's principles, showing small starting size, high growth, and clean efficiency ratios."
        elif label == "Moderate Potential":
            explanation += " This stock meets several key criteria but fails some checks, representing a moderate potential candidate."
        elif label == "Low Potential":
            explanation += " This stock fails multiple 100-bagger checks, showing high leverage, low growth, or excessive valuation."
            
        return BaggerCandidate(
            ticker=metrics.ticker,
            company_name=metrics.company_name,
            passed=passed,
            score=round(score, 2),
            pass_ratio=round(pass_ratio, 4),
            label=label,
            checks=checks,
            missing_fields=missing_fields,
            warnings=warnings,
            metrics=metrics_dict,
            explanation=explanation
        )

    @classmethod
    async def _fetch_and_evaluate_sem(
        cls, 
        symbol: str, 
        sem: asyncio.Semaphore, 
        config: BaggerFilterConfig
    ) -> Tuple[str, Optional[StockMetrics], Optional[BaggerCandidate], Optional[str]]:
        async with sem:
            try:
                loop = asyncio.get_event_loop()
                metrics = await loop.run_in_executor(None, cls.get_stock_metrics, symbol)
                candidate = cls.evaluate_candidate(metrics, config)
                return symbol, metrics, candidate, None
            except Exception as e:
                logger.error(f"Error evaluating {symbol} in background queue: {e}")
                return symbol, None, None, str(e)

    @classmethod
    async def scan_universe(
        cls, 
        tickers: List[str], 
        config: BaggerFilterConfig
    ) -> Tuple[List[BaggerCandidate], List[str], List[str], List[str]]:
        """Scan a list of tickers in parallel and filter candidates."""
        sanitized_tickers = sorted(list(set([t.strip().upper() for t in tickers if t.strip()])))
        
        sem = asyncio.Semaphore(config.max_concurrency)
        tasks = [
            cls._fetch_and_evaluate_sem(ticker, sem, config)
            for ticker in sanitized_tickers
        ]
        
        raw_results = await asyncio.gather(*tasks)
        
        candidates = []
        query_failures = []
        failed_screening = []
        insufficient = []
        
        for symbol, metrics, candidate, err in raw_results:
            if err or metrics is None or candidate is None:
                query_failures.append(symbol)
                candidates.append(
                    BaggerCandidate(
                        ticker=symbol,
                        passed=False,
                        score=0.0,
                        pass_ratio=0.0,
                        label="Low Potential",
                        checks=[],
                        missing_fields=["all"],
                        warnings=[f"Data query failed: {err or 'Unknown error'}"],
                        metrics={},
                        explanation=f"Scanning failed for {symbol} due to Yahoo Finance connection errors."
                    )
                )
                continue
                
            candidates.append(candidate)
            if candidate.label == "Insufficient Data":
                insufficient.append(symbol)
            elif not candidate.passed:
                failed_screening.append(symbol)
                
        candidates.sort(key=lambda x: (x.score, x.pass_ratio), reverse=True)
        return candidates, query_failures, failed_screening, insufficient

    @classmethod
    async def run_background_scan(cls, limit: Optional[int] = None, market: str = "NSE"):
        """
        Runs the complete daily scan in a background thread/task and upserts results to DB.
        """
        from app.models.base import SessionLocal
        from app.models.trading import NSEBaggerScanResult, USBaggerScanResult
        import time
        
        market_upper = market.upper().strip()
        is_us = (market_upper == "US")
        db_model = USBaggerScanResult if is_us else NSEBaggerScanResult
        
        logger.info(f"Starting Daily Background {market_upper} 100-Bagger Scanning Job...")
        start_time = time.time()
        
        db = SessionLocal()
        try:
            if is_us:
                logger.info("Fetching active symbols registry from US Market...")
                symbols = cls.fetch_us_symbols()
            else:
                logger.info("Fetching active symbols registry from NSE...")
                symbols = cls.fetch_nse_symbols()
            
            # Query existing tickers in database to exclude them
            try:
                existing_records = db.query(db_model.ticker).all()
                existing_tickers = {r.ticker.upper().strip() for r in existing_records}
            except Exception as db_err:
                logger.warning(f"Failed to query existing tickers from DB: {db_err}")
                existing_tickers = set()
                
            # Filter remaining tickers that are not already scanned
            remaining_symbols = []
            for sym in symbols:
                ticker_to_check = sym.strip().upper() if is_us else f"{sym.strip().upper()}.NS"
                if ticker_to_check not in existing_tickers:
                    remaining_symbols.append(sym)
            
            logger.info(f"Registry total: {len(symbols)}. Existing in DB: {len(existing_tickers)}. Remaining unscanned: {len(remaining_symbols)}")
            
            # Slice list to next batch (defaulting to 500 unscanned stocks if limit is not set)
            scan_limit = limit if limit is not None else 500
            symbols = remaining_symbols[:scan_limit]
            logger.info(f"Scanning list limited to next {len(symbols)} unscanned symbols.")
                
            stocks_fetched = len(symbols)
            stocks_scanned = 0
            stocks_updated = 0
            stocks_created = 0
            stocks_failed = 0
            
            stocks_high_potential = 0
            stocks_moderate_potential = 0
            stocks_low_potential = 0
            stocks_insufficient_data = 0
            
            config = BaggerFilterConfig()
            if is_us:
                # Default lower promoter holdings threshold for US stock institutional setups
                config.min_promoter_holding = 5.0
                
            batch_size = 10
            total_symbols = len(symbols)
            
            for i in range(0, total_symbols, batch_size):
                batch = symbols[i:i+batch_size]
                batch_tickers = batch if is_us else [f"{sym}.NS" for sym in batch]
                
                try:
                    candidates, query_failures, failed_list, insufficient_list = await cls.scan_universe(
                        tickers=batch_tickers,
                        config=config
                    )
                    
                    for cand in candidates:
                        if cand.ticker in query_failures:
                            stocks_failed += 1
                            continue
                            
                        stocks_scanned += 1
                        if cand.label == "High Potential":
                            stocks_high_potential += 1
                        elif cand.label == "Moderate Potential":
                            stocks_moderate_potential += 1
                        elif cand.label == "Low Potential":
                            stocks_low_potential += 1
                        elif cand.label == "Insufficient Data":
                            stocks_insufficient_data += 1
                            
                        checks_json = sanitize_for_json([check.model_dump() for check in cand.checks])
                        metrics_json = sanitize_for_json(cand.metrics)
                        db_record = db.query(db_model).filter(db_model.ticker == cand.ticker).first()
                        
                        if db_record:
                            db_record.company_name = cand.company_name
                            db_record.passed = cand.passed
                            db_record.score = cand.score
                            db_record.pass_ratio = cand.pass_ratio
                            db_record.label = cand.label
                            db_record.metrics = metrics_json
                            db_record.checks = checks_json
                            db_record.warnings = cand.warnings
                            db_record.missing_fields = cand.missing_fields
                            db_record.explanation = cand.explanation
                            stocks_updated += 1
                        else:
                            new_record = db_model(
                                ticker=cand.ticker,
                                company_name=cand.company_name,
                                passed=cand.passed,
                                score=cand.score,
                                pass_ratio=cand.pass_ratio,
                                label=cand.label,
                                metrics=metrics_json,
                                checks=checks_json,
                                warnings=cand.warnings,
                                missing_fields=cand.missing_fields,
                                explanation=cand.explanation
                            )
                            db.add(new_record)
                            stocks_created += 1
                    
                    db.commit()
                    logger.info(f"Background Batch completed. Cumulative processed: {stocks_scanned + stocks_failed}/{total_symbols}.")
                    await asyncio.sleep(1.0)
                    
                except Exception as batch_err:
                    logger.error(f"Error executing background batch starting at index {i}: {batch_err}")
                    db.rollback()
                    
            elapsed = time.time() - start_time
            avg_speed_ms = round((elapsed * 1000) / stocks_scanned, 1) if stocks_scanned > 0 else 0.0
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            
            summary_msg = f"""
=============================SCAN SCHEDULER SUMMARY START=========================
[Core Scan Statistics]
Number of stocks fetched - {stocks_fetched}
Number of stocks scanned - {stocks_scanned}
Number of stocks failed to scan - {stocks_failed}

[Database Operations]
Number of stocks updated in DB - {stocks_updated}
Number of stocks created in DB - {stocks_created}

[Quantitative Screening Results]
High Potential Candidates (Passed 100-Bagger) - {stocks_high_potential}
Moderate Potential Candidates - {stocks_moderate_potential}
Low Potential Candidates - {stocks_low_potential}
Insufficient Data Candidates (Skipped) - {stocks_insufficient_data}

[Data Diagnostics & Performance]
Total Elapsed Time - {time_str}
Average Scan Speed - {avg_speed_ms} ms/stock
=============================SCAN SCHEDULER SUMMARY END===========================
"""
            print(summary_msg)
            logger.info(f"Background NSE 100-Bagger Scanning Job completed in {elapsed:.2f} seconds!")
            
        except Exception as e:
            logger.critical(f"Background daily cron scanner crashed: {e}")
        finally:
            db.close()

    @classmethod
    def enrich_candidate_qualitative_quantitative(
        cls, 
        candidate: BaggerCandidate, 
        metrics: StockMetrics, 
        run_quant: bool, 
        run_qual: bool
    ) -> BaggerCandidate:
        """
        Enrich a BaggerCandidate with additional quantitative flags and/or qualitative scoring
        based on active request headers/parameters.
        """
        deprioritized = False
        quant_flags = []
        
        # Calculate ROIC 5-year average
        roic_vals = [m.value for m in metrics.roic_history if m.value is not None]
        roic_5y_avg = sum(roic_vals) / len(roic_vals) if roic_vals else None
        
        # Save roic_5y_avg in metrics dict for sorting later
        candidate.metrics["roic_5y_avg"] = roic_5y_avg
        
        # Stage 1: Additional Quantitative Filters
        if run_quant:
            # 1. Insider ownership < 10%
            insider = metrics.promoter_holding
            if insider is None or insider < 10.0:
                deprioritized = True
                val_str = f"{insider:.2f}%" if insider is not None else "N/A"
                quant_flags.append(f"Insider ownership < 10% (Actual: {val_str})")
                
            # 2. ROIC 5y average < 15%
            if roic_5y_avg is None or roic_5y_avg < 15.0:
                deprioritized = True
                val_str = f"{roic_5y_avg:.2f}%" if roic_5y_avg is not None else "N/A"
                quant_flags.append(f"ROIC 5y average < 15% (Actual: {val_str})")
                
            # 3. Debt-to-equity > 1.0
            debt_eq = metrics.debt_to_equity
            if debt_eq is None or debt_eq > 1.0:
                deprioritized = True
                val_str = f"{debt_eq:.2f}" if debt_eq is not None else "N/A"
                quant_flags.append(f"Debt-to-equity > 1.0 (Actual: {val_str})")
                
            # 4. Missing critical fields
            missing_fields = []
            if metrics.market_cap is None:
                missing_fields.append("marketCap")
            if not metrics.revenue_history:
                missing_fields.append("revenueHistory")
            if not metrics.eps_history:
                missing_fields.append("epsHistory")
            if metrics.roe is None:
                missing_fields.append("roe")
            if metrics.operating_margin is None:
                missing_fields.append("operatingMargins")
            if metrics.debt_to_equity is None:
                missing_fields.append("debtToEquity")
            if metrics.promoter_holding is None:
                missing_fields.append("heldPercentInsiders")
                
            if missing_fields:
                deprioritized = True
                quant_flags.append(f"Missing critical fields: {', '.join(missing_fields)}")
                
            candidate.deprioritized = deprioritized
            candidate.quantitative_flags = quant_flags
        else:
            candidate.deprioritized = False
            candidate.quantitative_flags = []
            
        # Stage 2: Structured Qualitative Scoring (Total 90 points)
        if run_qual:
            qual_breakdown = {}
            
            # 1. Consistency of high returns (ROE/ROIC) (0-12 points)
            high_return_points = 6
            if metrics.roe is not None and metrics.roe >= 15.0:
                high_return_points += 3
            if roic_5y_avg is not None and roic_5y_avg >= 15.0:
                high_return_points += 3
            if metrics.roic_history:
                under_15_count = sum(1 for m in metrics.roic_history if m.value < 15.0)
                if under_15_count == 0:
                    high_return_points = min(12, high_return_points + 3)
            qual_breakdown["high_returns_consistency"] = float(high_return_points)
            
            # 2. Growth quality & longevity (0-10 points)
            growth_points = 4
            rev_cagr = cls._calculate_cagr(metrics.revenue_history)
            eps_cagr = cls._calculate_cagr(metrics.eps_history)
            if rev_cagr is not None and rev_cagr >= 20.0:
                growth_points += 3
            elif rev_cagr is not None and rev_cagr >= 15.0:
                growth_points += 2
            if eps_cagr is not None and eps_cagr >= 20.0:
                growth_points += 3
            elif eps_cagr is not None and eps_cagr >= 15.0:
                growth_points += 2
            qual_breakdown["growth_quality_longevity"] = float(growth_points)
            
            # 3. Capital efficiency & FCF conversion (0-8 points)
            fcf_points = 3
            if metrics.ocf_to_net_income_ratio is not None and metrics.ocf_to_net_income_ratio >= 1.0:
                fcf_points += 3
            elif metrics.ocf_to_net_income_ratio is not None and metrics.ocf_to_net_income_ratio >= 0.8:
                fcf_points += 2
            
            raw_info = metrics.dict().get("_raw_info") or {}
            fcf_val = raw_info.get("freeCashflow") or metrics.dict().get("free_cash_flow")
            if fcf_val and metrics.market_cap and metrics.market_cap > 0:
                fcf_margin = (fcf_val / metrics.market_cap) * 100.0
                if fcf_margin >= 5.0:
                    fcf_points += 2
            qual_breakdown["capital_efficiency_fcf_conversion"] = float(min(8, fcf_points))
            
            # 4. Balance sheet strength beyond D/E (0-5 points)
            bs_points = 2
            debt = metrics.debt_to_equity
            if debt is not None and debt < 0.2:
                bs_points += 2
            elif debt is not None and debt < 0.5:
                bs_points += 1
            if metrics.ocf_to_net_income_ratio is not None and metrics.ocf_to_net_income_ratio >= 1.2:
                bs_points += 1
            qual_breakdown["balance_sheet_strength"] = float(min(5, bs_points))
            
            # 5. Valuation buffer (PE relative to growth) (0-5 points)
            val_points = 1
            pe = metrics.trailing_pe
            cagr = rev_cagr or 15.0
            if pe and cagr:
                peg = pe / cagr
                if peg <= 1.0:
                    val_points = 5
                elif peg <= 1.5:
                    val_points = 4
                elif peg <= 2.0:
                    val_points = 3
                else:
                    val_points = 2
            qual_breakdown["valuation_buffer"] = float(val_points)
            
            # 6. Moat durability (0-12 points)
            moat_points = 4
            margin = metrics.operating_margin
            if margin is not None:
                if margin >= 25.0:
                    moat_points += 6
                elif margin >= 15.0:
                    moat_points += 4
                elif margin >= 10.0:
                    moat_points += 2
            
            comp_name_lower = (candidate.company_name or "").lower()
            is_tech_saas = any(k in comp_name_lower or k in candidate.explanation.lower() for k in ["software", "tech", "saas", "digital", "data", "consulting"])
            if is_tech_saas:
                moat_points += 2
            qual_breakdown["moat_durability"] = float(min(12, moat_points))
            
            # 7. TAM & runway (0-12 points)
            tam_points = 5
            mcap_val = metrics.market_cap
            is_us = not (candidate.ticker.endswith(".NS") or candidate.ticker.endswith(".BO"))
            if mcap_val:
                if is_us and mcap_val < 300000000.0:
                    tam_points += 5
                elif is_us and mcap_val < 800000000.0:
                    tam_points += 3
                elif not is_us and mcap_val < 1000000000.0:
                    tam_points += 5
                elif not is_us and mcap_val < 5000000000.0:
                    tam_points += 3
            qual_breakdown["tam_runway"] = float(tam_points)
            
            # 8. Management & ownership quality (0-10 points)
            mgmt_points = 2
            insider = metrics.promoter_holding
            if insider is not None:
                if insider >= 50.0:
                    mgmt_points += 7
                elif insider >= 30.0:
                    mgmt_points += 5
                elif insider >= 10.0:
                    mgmt_points += 3
            qual_breakdown["management_ownership_quality"] = float(mgmt_points)
            
            # 9. Reinvestment opportunity (0-10 points)
            reinvest_points = 3
            if roic_5y_avg is not None and roic_5y_avg >= 20.0:
                reinvest_points += 5
            elif roic_5y_avg is not None and roic_5y_avg >= 15.0:
                reinvest_points += 3
            qual_breakdown["reinvestment_opportunity"] = float(min(10, reinvest_points))
            
            # 10. Business model resilience & optionality (0-6 points)
            resilience_points = 3
            if margin is not None and margin >= 20.0:
                resilience_points += 2
            qual_breakdown["business_model_resilience"] = float(min(6, resilience_points))
            
            qualitative_score = sum(qual_breakdown.values())
            candidate.qualitative_score = qualitative_score
            candidate.qualitative_breakdown = qual_breakdown
            candidate.composite_score = candidate.score + qualitative_score
            
            comp = candidate.composite_score
            if comp >= 150.0:
                confidence_level = "High"
            elif comp >= 120.0:
                confidence_level = "Medium"
            else:
                confidence_level = "Low"
            candidate.confidence_level = confidence_level
            
            name = candidate.company_name or candidate.ticker
            mcap_str = f"${mcap_val/1e6:.1f}M USD" if is_us else f"₹{mcap_val/1e7:.1f} Cr INR"
            
            candidate.thesis_summary = (
                f"{name} ({candidate.ticker}) exhibits a classic capital-light compounder model with high capital efficiency "
                f"(ROE: {metrics.roe or 0:.1f}%, ROIC 5y Avg: {roic_5y_avg or 0:.1f}%). Valued at a reasonable trailing P/E of "
                f"{metrics.trailing_pe or 'N/A'}x and with a small starting size of {mcap_str}, it has a significant runway "
                f"to reinvest operating cash flows into high-return growth opportunities for multiple decades."
            )
            
            risks = [
                "Intensifying competitive pressure eroding premium pricing power",
                "Management execution errors in expanding geographic footprint or product optionality",
                "Sensitivity to macro-economic slowdowns impacting end-user market demand"
            ]
            if metrics.debt_to_equity and metrics.debt_to_equity > 0.5:
                risks.append("Leverage risks associated with debt service coverage under high-interest regimes")
            candidate.kill_risks = risks[:3]
        else:
            candidate.qualitative_score = None
            candidate.qualitative_breakdown = None
            candidate.composite_score = candidate.score
            candidate.thesis_summary = None
            candidate.kill_risks = None
            candidate.confidence_level = None
            
        return candidate

    @classmethod
    def evaluate_safety_filters(
        cls, 
        candidate: BaggerCandidate, 
        metrics: StockMetrics, 
        run_safety: bool
    ) -> BaggerCandidate:
        """
        Evaluate candidate against strict micro-cap safety and integrity checks.
        If any safety rule fails, set safety_failed = True, deprioritized = True,
        and append warning details to safety_flags.
        """
        if not run_safety:
            candidate.safety_failed = False
            candidate.safety_flags = []
            return candidate

        safety_failed = False
        safety_flags = []

        # 1. Cash Flow Integrity (The "Paper vs. Real" Filter)
        # CFO / EBITDA > 70%
        cfo_ebitda = metrics.cfo_to_ebitda_avg
        if cfo_ebitda is not None:
            if cfo_ebitda < 0.70:
                safety_failed = True
                safety_flags.append(f"CFO / EBITDA is less than 70% (Actual: {cfo_ebitda * 100:.1f}%)")
        else:
            # Fallback to single year check if average is not calculated
            if metrics.ocf_to_net_income_ratio is not None and metrics.ocf_to_net_income_ratio < 0.70:
                safety_failed = True
                safety_flags.append(f"CFO captures less than 70% of net profits (Actual: {metrics.ocf_to_net_income_ratio * 100:.1f}%)")

        # Negative Free Cash Flow Safeguard
        raw_info = metrics.dict().get("_raw_info") or {}
        fcf_val = raw_info.get("freeCashflow") or metrics.dict().get("free_cash_flow")
        ocf_val = raw_info.get("operatingCashflow") or (metrics.ocf_to_net_income_ratio * (metrics.market_cap / (metrics.trailing_pe or 20.0)) if metrics.market_cap and metrics.ocf_to_net_income_ratio and metrics.trailing_pe else None)
        
        if fcf_val is not None and fcf_val < 0:
            if ocf_val is not None and ocf_val < 0:
                safety_failed = True
                safety_flags.append("Negative Free Cash Flow driven by negative Operating Cash Flow (unproductive deficit)")

        # 2. Working Capital & Liquidity Health
        # Accounts receivable growth vs Sales growth
        sorted_rec = sorted(metrics.receivables_history, key=lambda x: x.year)
        sorted_rev = sorted(metrics.revenue_history, key=lambda x: x.year)
        if len(sorted_rec) >= 2 and len(sorted_rev) >= 2:
            try:
                rec_growth = ((sorted_rec[-1].value / sorted_rec[-2].value) - 1.0) * 100.0 if sorted_rec[-2].value and sorted_rec[-2].value > 0 else None
                rev_growth = ((sorted_rev[-1].value / sorted_rev[-2].value) - 1.0) * 100.0 if sorted_rev[-2].value and sorted_rev[-2].value > 0 else None
                if rec_growth is not None and rev_growth is not None and rec_growth > rev_growth:
                    safety_failed = True
                    safety_flags.append(f"Accounts receivable growth ({rec_growth:.1f}%) exceeds revenue growth ({rev_growth:.1f}%)")
            except Exception:
                pass

        # Exit Liquidity limit
        is_us = not (candidate.ticker.endswith(".NS") or candidate.ticker.endswith(".BO"))
        mcap_val = metrics.market_cap
        price_val = metrics.current_price
        vol_val = metrics.average_volume
        
        if vol_val and price_val:
            daily_market_volume = vol_val * price_val
            exit_limit = 100000000.0 if not is_us else 1000000.0 # ₹10 Cr INR for India, $1M USD for US
            if daily_market_volume < exit_limit:
                safety_failed = True
                currency_symbol = "$" if is_us else "₹"
                denom = 1e6 if is_us else 1e7
                unit = "M" if is_us else "Cr"
                safety_failed = True
                safety_flags.append(
                    f"Insufficient trading liquidity (Daily market volume: {currency_symbol}{daily_market_volume/denom:.2f} {unit} is below safety exit limit)"
                )

        # 3. Structural Growth & Profitability
        # ROE > 20% for 3 years (using current ROE and 5-year average ROIC as structural indicators)
        roic_vals = [m.value for m in metrics.roic_history if m.value is not None]
        roic_5y_avg = sum(roic_vals) / len(roic_vals) if roic_vals else None
        
        if metrics.roe is not None and metrics.roe < 20.0:
            safety_failed = True
            safety_flags.append(f"Return on Equity (ROE: {metrics.roe:.1f}%) does not hold above 20.0% structurally")
        elif roic_5y_avg is not None and roic_5y_avg < 20.0:
            safety_failed = True
            safety_flags.append(f"Average 5y ROIC ({roic_5y_avg:.1f}%) is below 20.0% structural limit")

        # 4. Corporate Governance & Transparency
        # Zero promoter shares pledged
        if metrics.pledged_percentage is not None and metrics.pledged_percentage > 0.0:
            safety_failed = True
            safety_flags.append(f"Promoter shares are pledged (Pledged percentage: {metrics.pledged_percentage:.2f}%)")

        candidate.safety_failed = safety_failed
        candidate.safety_flags = safety_flags
        
        # If safety fails, deprioritize candidate in sorting
        if safety_failed:
            candidate.deprioritized = True
            
        return candidate

