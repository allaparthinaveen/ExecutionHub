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

# Cache for NSE symbol list (24 hours TTL)
nse_symbols_cache = TTLCache(maxsize=1, ttl=86400)

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
            
        # Return a basic default backup list of major NSE symbols if download fails
        backup_list = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL",
            "SBI", "LICI", "ITC", "HINDUNILVR", "LT", "BAJFINANCE", "HCLTECH",
            "MARUTI", "SUNPHARMA", "ADANIENT", "KOTAKBANK", "TITAN", "AXISBANK",
            "DELHIVERY", "ZOMATO"
        ]
        return backup_list

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
        except Exception as e:
            logger.error(f"Error scraping Screener.in for {clean_symbol}: {e}")
            
        return data

    @classmethod
    def get_stock_metrics(cls, symbol: str) -> StockMetrics:
        """Fetch and normalize financial metrics for a symbol using YahooFinanceClient."""
        yf_symbol = symbol.strip().upper()
        if not yf_symbol.endswith(".NS") and not yf_symbol.endswith(".BO") and "^" not in yf_symbol:
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
                
        # Promoter Holding
        promoter_holding = YahooFinanceClient.extract_float_metric(info, ["heldPercentInsiders", "insiderOwnersPercent"])
        if promoter_holding is not None:
            promoter_holding = promoter_holding * 100.0
            
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
        if is_indian_stock and (not revenue_history or market_cap is None or roe is None or promoter_holding is None or debt_to_equity is None):
            logger.info(f"Yfinance data incomplete for Indian stock {yf_symbol}; querying Screener.in fallback...")
            screener_data = cls.scrape_screener_in(yf_symbol)
            if screener_data:
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
                if not revenue_history and "revenue_history" in screener_data:
                    for item in screener_data["revenue_history"]:
                        revenue_history.append(YearlyMetric(year=item["year"], value=item["value"]))
                if not eps_history and "eps_history" in screener_data:
                    for item in screener_data["eps_history"]:
                        eps_history.append(YearlyMetric(year=item["year"], value=item["value"]))
                        
        return StockMetrics(
            ticker=yf_symbol,
            company_name=info.get("longName") or info.get("shortName") or symbol,
            currency=info.get("currency") or "INR",
            market_cap=market_cap,
            current_price=current_price,
            trailing_pe=trailing_pe,
            forward_pe=forward_pe,
            roe=roe,
            operating_margin=op_margin,
            debt_to_equity=debt_to_equity,
            promoter_holding=promoter_holding,
            revenue_history=revenue_history,
            eps_history=eps_history
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
            
        # Final calculations
        score = (achieved_weight / possible_weight) * 100.0 if possible_weight > 0 else 0.0
        pass_ratio = passed_checks / evaluable_checks if evaluable_checks > 0 else 0.0
        
        # Classification Mapping
        if possible_weight < 50.0:
            label = "Insufficient Data"
        elif score >= 80.0 and pass_ratio >= config.min_pass_ratio:
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
