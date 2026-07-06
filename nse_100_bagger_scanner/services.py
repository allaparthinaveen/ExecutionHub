import logging
import math
import asyncio
from typing import Dict, Any, List, Tuple, Optional
from nse_100_bagger_scanner.models import (
    BaggerFilterConfig,
    StockMetrics,
    ScreenerCheckResult,
    BaggerCandidate,
    YearlyMetric
)
from nse_100_bagger_scanner.utils import (
    get_ticker_info,
    get_ticker_statements,
    get_yf_ticker,
    extract_statement_metric,
    extract_float_metric
)

logger = logging.getLogger("nse_100_bagger.services")

class BaggerScannerService:
    @staticmethod
    def _calculate_cagr(history: List[YearlyMetric]) -> Optional[float]:
        """Calculate compound annual growth rate (%) over available history."""
        if len(history) < 2:
            return None
        # Sort history by year ascending
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
    def get_stock_metrics(cls, symbol: str) -> StockMetrics:
        """Fetch and normalize financial metrics for a symbol."""
        # Sanitize symbol by adding .NS if not present
        yf_symbol = symbol.strip().upper()
        if not yf_symbol.endswith(".NS") and not yf_symbol.endswith(".BO") and "^" not in yf_symbol:
            yf_symbol = f"{yf_symbol}.NS"
            
        info = get_ticker_info(yf_symbol)
        statements = get_ticker_statements(yf_symbol)
        
        fin_df = statements["financials"]
        bs_df = statements["balance_sheet"]
        cf_df = statements["cashflow"]
        
        # 1. Base Info
        current_price = extract_float_metric(info, ["currentPrice", "regularMarketPrice", "navPrice"])
        market_cap = extract_float_metric(info, ["marketCap", "regularMarketVolume"])
        trailing_pe = extract_float_metric(info, ["trailingPE"])
        forward_pe = extract_float_metric(info, ["forwardPE"])
        roe = extract_float_metric(info, ["returnOnEquity"])
        op_margin = extract_float_metric(info, ["operatingMargins"])
        
        # Convert decimal ROE and Operating Margins to percentage
        if roe is not None:
            roe = roe * 100.0
        if op_margin is not None:
            op_margin = op_margin * 100.0
            
        # Debt to Equity
        debt_to_equity = extract_float_metric(info, ["debtToEquity"])
        if debt_to_equity is not None:
            # yfinance returns debtToEquity as percentage (e.g. 79.5 meaning 0.795 ratio)
            debt_to_equity = debt_to_equity / 100.0
        else:
            # Fallback to balance sheet
            try:
                total_debt_list = extract_statement_metric(bs_df, ["Total Debt", "Net Debt"])
                equity_list = extract_statement_metric(bs_df, ["Stockholders Equity", "Common Stock Equity"])
                if total_debt_list and equity_list and equity_list[0] and equity_list[0] > 0:
                    debt_to_equity = total_debt_list[0] / equity_list[0]
            except Exception:
                pass
                
        # Promoter/Insider holding (heldPercentInsiders or insiderOwnersPercent)
        promoter_holding = extract_float_metric(info, ["heldPercentInsiders", "insiderOwnersPercent"])
        if promoter_holding is not None:
            promoter_holding = promoter_holding * 100.0
            
        # 2. Extract Revenue & EPS History
        revenue_history = []
        eps_history = []
        
        # Revenue rows fallback
        rev_rows = ["Total Revenue", "Operating Revenue", "Revenue"]
        rev_vals = extract_statement_metric(fin_df, rev_rows)
        if rev_vals:
            # Extract years from financial columns
            years = []
            for col in fin_df.columns:
                try:
                    years.append(pd.to_datetime(col).year)
                except Exception:
                    years.append(None)
            for yr, val in zip(years, rev_vals):
                if yr is not None and val is not None and val > 0:
                    revenue_history.append(YearlyMetric(year=int(yr), value=float(val)))
                    
        # EPS rows fallback
        eps_rows = ["Diluted EPS", "Basic EPS"]
        eps_vals = extract_statement_metric(fin_df, eps_rows)
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
        # Christopher Mayer principle: Start small (market cap < 5,000 Crore INR)
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
        # 100-baggers are driven first and foremost by revenue growth
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
        # High earnings growth multiplies the compound return
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
            
        # 4. Return on Capital Efficiency Check (Weight 20)
        # Consistent high return on capital (ROE/ROIC > 15-20%) represents compounding efficiency
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
        # Higher gross/operating margins represent a strong business moat
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
        # Avoiding high multiples allows for PE multiple expansion
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
        # "Skin in the game": Owner-operator stocks with high promoter holding (India-specific)
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
        # Low leverage helps survive cycles
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
        
        # Build metrics dict for JSON output
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
        """Fetch and evaluate a single stock wrapped in a semaphore for parallel execution."""
        async with sem:
            try:
                loop = asyncio.get_event_loop()
                metrics = await loop.run_in_executor(None, cls.get_stock_metrics, symbol)
                candidate = cls.evaluate_candidate(metrics, config)
                return symbol, metrics, candidate, None
            except Exception as e:
                logger.error(f"Error evaluating {symbol}: {e}")
                return symbol, None, None, str(e)

    @classmethod
    async def scan_universe(
        cls, 
        tickers: List[str], 
        config: BaggerFilterConfig
    ) -> Tuple[List[BaggerCandidate], List[str], List[str], List[str]]:
        """Scan a list of tickers in parallel and filter candidates."""
        # Sanitize and deduplicate tickers list
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
                # Append a failed candidate object so we keep track
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
                
        # Sort candidates by score descending, then pass_ratio descending
        candidates.sort(key=lambda x: (x.score, x.pass_ratio), reverse=True)
        return candidates, query_failures, failed_screening, insufficient
