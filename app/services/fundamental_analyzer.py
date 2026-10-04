import logging
import math
from typing import Dict, Any, List, Tuple
from app.schemas.fundamentals import (
    FundamentalsResponse,
    YearlyEPS,
    ScanConfig,
    ScreenerResult
)
from app.services.yahoo_client import YahooFinanceClient

logger = logging.getLogger("tradeservices.fundamental_analyzer")

class FundamentalAnalyzer:
    """
    Business logic class that performs Graham-style defensive checks,
    computes scores, and handles classification logic.
    """

    @classmethod
    def analyze_ticker(cls, normalized_metrics: Dict[str, Any], config: ScanConfig) -> Dict[str, Any]:
        """
        Evaluate a single ticker's normalized metrics against the specified ScanConfig.
        Returns check results, reasons, warnings, and overall scores.
        """
        reasons_passed = []
        reasons_failed = []
        missing_fields = []
        warnings = []
        
        achieved_weight = 0.0
        possible_weight = 0.0
        evaluable_checks = 0
        passed_checks = 0

        # Extract values
        mcap = normalized_metrics.get("market_cap")
        current_ratio = normalized_metrics.get("current_ratio")
        lt_debt = normalized_metrics.get("long_term_debt")
        wc = normalized_metrics.get("working_capital")
        eps_history = normalized_metrics.get("eps_history") or []
        dividend_paying = normalized_metrics.get("dividend_paying", False)
        pe = normalized_metrics.get("trailing_pe")
        pb = normalized_metrics.get("price_to_book")
        op_cf = normalized_metrics.get("operating_cash_flow")
        fcf = normalized_metrics.get("free_cash_flow")

        # ----------------------------------------------------
        # Rule 1: Size (Market Cap) - Weight 5
        # ----------------------------------------------------
        if mcap is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            if mcap >= config.min_market_cap:
                achieved_weight += 5.0
                passed_checks += 1
                reasons_passed.append(f"Market capitalization ${mcap/1e9:.2f}B >= ${config.min_market_cap/1e9:.2f}B")
            else:
                reasons_failed.append(f"Market capitalization ${mcap/1e9:.2f}B is below required ${config.min_market_cap/1e9:.2f}B")
        else:
            missing_fields.append("marketCap")
            warnings.append("Market capitalization unavailable; size check skipped.")

        # ----------------------------------------------------
        # Rule 2: Current Ratio - Weight 15
        # ----------------------------------------------------
        curr_assets = normalized_metrics.get("total_current_assets")
        curr_liab = normalized_metrics.get("total_current_liabilities")
        if current_ratio is None and curr_assets is not None and curr_liab and curr_liab > 0:
            current_ratio = curr_assets / curr_liab
            
        if current_ratio is not None:
            possible_weight += 15.0
            evaluable_checks += 1
            if current_ratio >= config.min_current_ratio:
                achieved_weight += 15.0
                passed_checks += 1
                reasons_passed.append(f"Current ratio {current_ratio:.2f} >= {config.min_current_ratio:.1f}")
            else:
                reasons_failed.append(f"Current ratio {current_ratio:.2f} is below required {config.min_current_ratio:.1f}")
        else:
            missing_fields.append("currentRatio")
            warnings.append("Current ratio data unavailable; liquidity check skipped.")

        # ----------------------------------------------------
        # Rule 3: Debt vs Working Capital - Weight 20
        # ----------------------------------------------------
        if lt_debt is not None and wc is not None:
            possible_weight += 20.0
            evaluable_checks += 1
            if lt_debt <= wc:
                achieved_weight += 20.0
                passed_checks += 1
                reasons_passed.append(f"Long-term debt ${lt_debt/1e6:.1f}M <= working capital ${wc/1e6:.1f}M")
            else:
                reasons_failed.append(f"Long-term debt ${lt_debt/1e6:.1f}M exceeds working capital ${wc/1e6:.1f}M")
        else:
            missing_check_fields = []
            if lt_debt is None: missing_check_fields.append("longTermDebt")
            if wc is None: missing_check_fields.append("workingCapital")
            missing_fields.extend(missing_check_fields)
            warnings.append(f"Debt or Working Capital fields ({', '.join(missing_check_fields)}) missing; debt safety check skipped.")

        # ----------------------------------------------------
        # Rule 4: Earnings Stability - Weight 20
        # ----------------------------------------------------
        stability_pass = None
        if eps_history:
            possible_weight += 20.0
            evaluable_checks += 1
            # Check for negative EPS in any historical year
            negative_years = [y for y in eps_history if y.get("eps") is not None and y.get("eps") < 0]
            num_years = len(eps_history)
            
            if num_years < config.eps_history_years:
                warnings.append(f"Only {num_years} years of EPS history available; applied partial stability evaluation.")
                
            if not negative_years:
                stability_pass = True
                achieved_weight += 20.0
                passed_checks += 1
                reasons_passed.append(f"No negative EPS years found in the last {num_years} years of history.")
            else:
                stability_pass = False
                neg_details = ", ".join([f"{y['year']}: {y['eps']:.2f}" for y in negative_years])
                reasons_failed.append(f"Negative EPS found in years: {neg_details}")
        else:
            missing_fields.append("epsHistory")
            warnings.append("No EPS history available; earnings stability check skipped.")

        # ----------------------------------------------------
        # Rule 5: Dividend Status/Record - Weight 10
        # ----------------------------------------------------
        # Always evaluable because we map missing to False in normalization
        possible_weight += 10.0
        evaluable_checks += 1
        if dividend_paying:
            achieved_weight += 10.0
            passed_checks += 1
            yield_val = normalized_metrics.get("dividend_yield")
            yield_str = f" (Yield: {yield_val*100:.2f}%)" if yield_val is not None else ""
            reasons_passed.append(f"Company currently pays dividends{yield_str}.")
        else:
            if config.require_dividend_paying:
                reasons_failed.append("Company is not registered as currently paying dividends.")
            else:
                reasons_passed.append("Company does not pay dividends (informational - not required by config).")

        # ----------------------------------------------------
        # Rule 6: Earnings Growth - Weight 10
        # ----------------------------------------------------
        growth_pct = None
        if len(eps_history) >= 3:
            possible_weight += 10.0
            evaluable_checks += 1
            # Sort just in case
            sorted_eps = sorted(eps_history, key=lambda x: x["year"])
            recent_avg = sum(y["eps"] for y in sorted_eps[-3:]) / 3.0
            
            if len(sorted_eps) >= 6:
                older_avg = sum(y["eps"] for y in sorted_eps[:3]) / 3.0
                growth_desc = "latest 3-year avg vs oldest 3-year avg"
            else:
                older_avg = sum(y["eps"] for y in sorted_eps[:2]) / 2.0
                growth_desc = "latest 3-year avg vs oldest 2-year avg"
                
            if older_avg != 0.0:
                growth_pct = ((recent_avg - older_avg) / abs(older_avg)) * 100.0
            else:
                growth_pct = 100.0 if recent_avg > older_avg else 0.0

            if growth_pct >= config.min_eps_growth_percent:
                achieved_weight += 10.0
                passed_checks += 1
                reasons_passed.append(f"Earnings growth of {growth_pct:.1f}% ({growth_desc}) meets min {config.min_eps_growth_percent}%")
            else:
                reasons_failed.append(f"Earnings growth of {growth_pct:.1f}% ({growth_desc}) is below min {config.min_eps_growth_percent}%")
        else:
            warnings.append("Insufficient years of EPS history to calculate earnings growth.")

        # ----------------------------------------------------
        # Rule 7: Trailing PE - Weight 10
        # ----------------------------------------------------
        pe_pass = None
        if pe is not None:
            possible_weight += 10.0
            evaluable_checks += 1
            if pe > 0 and pe <= config.max_trailing_pe:
                pe_pass = True
                achieved_weight += 10.0
                passed_checks += 1
                reasons_passed.append(f"Trailing PE ratio {pe:.2f} <= {config.max_trailing_pe:.1f}")
            else:
                pe_pass = False
                reasons_failed.append(f"Trailing PE ratio {pe:.2f} exceeds max {config.max_trailing_pe:.1f} (or is negative)")
        else:
            missing_fields.append("trailingPE")
            warnings.append("Trailing PE ratio unavailable; PE check skipped.")

        # ----------------------------------------------------
        # Rule 8: Price to Book - Weight 5
        # ----------------------------------------------------
        pb_pass = None
        if pb is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            if pb > 0 and pb <= config.max_price_to_book:
                pb_pass = True
                achieved_weight += 5.0
                passed_checks += 1
                reasons_passed.append(f"Price to Book ratio {pb:.2f} <= {config.max_price_to_book:.1f}")
            else:
                pb_pass = False
                reasons_failed.append(f"Price to Book ratio {pb:.2f} exceeds max {config.max_price_to_book:.1f} (or is negative)")
        else:
            missing_fields.append("priceToBook")
            warnings.append("Price to Book ratio unavailable; PB check skipped.")

        # ----------------------------------------------------
        # Rule 9: Combined PE * PB - Weight 5
        # ----------------------------------------------------
        combined_pass = None
        if pe is not None and pb is not None:
            possible_weight += 5.0
            evaluable_checks += 1
            if pe > 0 and pb > 0:
                product = pe * pb
                if product <= config.max_pe_pb_product:
                    combined_pass = True
                    achieved_weight += 5.0
                    passed_checks += 1
                    reasons_passed.append(f"Combined PE * PB multiplier {product:.2f} <= {config.max_pe_pb_product:.1f}")
                else:
                    combined_pass = False
                    reasons_failed.append(f"Combined PE * PB multiplier {product:.2f} exceeds max {config.max_pe_pb_product:.1f}")
            else:
                combined_pass = False
                reasons_failed.append("PE or PB is negative; combined valuation check failed.")
        else:
            warnings.append("Combined PE * PB check skipped due to missing PE or PB.")

        # ----------------------------------------------------
        # Quality Checks (Optional, but checked)
        # ----------------------------------------------------
        # Operating Cash Flow
        if config.require_positive_operating_cash_flow:
            if op_cf is not None:
                possible_weight += 5.0
                evaluable_checks += 1
                if op_cf > 0:
                    achieved_weight += 5.0
                    passed_checks += 1
                    reasons_passed.append(f"Operating cash flow is positive: ${op_cf/1e6:.1f}M")
                else:
                    reasons_failed.append(f"Operating cash flow is negative/zero: ${op_cf/1e6:.1f}M")
            else:
                missing_fields.append("operatingCashFlow")
                warnings.append("Operating cash flow unavailable; positive OCF check skipped.")

        # Free Cash Flow
        if config.require_positive_free_cash_flow:
            if fcf is not None:
                possible_weight += 5.0
                evaluable_checks += 1
                if fcf > 0:
                    achieved_weight += 5.0
                    passed_checks += 1
                    reasons_passed.append(f"Free cash flow is positive: ${fcf/1e6:.1f}M")
                else:
                    reasons_failed.append(f"Free cash flow is negative/zero: ${fcf/1e6:.1f}M")
            else:
                missing_fields.append("freeCashflow")
                warnings.append("Free cash flow unavailable; positive FCF check skipped.")

        # Calculate final scores
        score = (achieved_weight / possible_weight) * 100.0 if possible_weight > 0 else 0.0
        pass_ratio = passed_checks / evaluable_checks if evaluable_checks > 0 else 0.0

        # Classification mapping
        if possible_weight < 50.0:
            label = "Insufficient Data"
        elif score >= 80.0 and pass_ratio >= config.min_pass_ratio:
            label = "Strong"
        elif 60.0 <= score < 80.0:
            label = "Borderline"
        else:
            label = "Weak"

        passed = (label == "Strong")
        
        # Calculate Graham Number if valid
        graham_number = None
        latest_eps = eps_history[-1].get("eps") if eps_history else None
        
        bvps = None
        shs = normalized_metrics.get("shares_outstanding")
        eq = normalized_metrics.get("stockholders_equity")
        price = normalized_metrics.get("current_price")
        
        if eq and shs and shs > 0:
            bvps = eq / shs
        elif pb and pb > 0 and price:
            bvps = price / pb
            
        if latest_eps is not None and latest_eps > 0 and bvps is not None and bvps > 0:
            graham_number = math.sqrt(22.5 * latest_eps * bvps)

        explanation = (
            f"{normalized_metrics.get('company_name')} ({normalized_metrics['ticker']}) "
            f"classified as {label} with a score of {score:.1f}% (evaluated on {passed_checks}/{evaluable_checks} checks). "
        )
        if passed:
            explanation += "This company aligns strongly with Benjamin Graham's defensive value investing profile, showing solid financial protection and value criteria."
        elif label == "Borderline":
            explanation += "This company meets several Graham criteria but fails some checks or lacks complete data, representing a borderline candidate."
        elif label == "Weak":
            explanation += "This company fails critical Graham defensive checks, suggesting higher risk or elevated valuation."
        else:
            explanation += "Not enough required financial metrics were available from Yahoo Finance to complete a reliable defensive investor analysis."

        return {
            "passed": passed,
            "score": round(score, 2),
            "pass_ratio": round(pass_ratio, 4),
            "label": label,
            "reasons_passed": reasons_passed,
            "reasons_failed": reasons_failed,
            "missing_fields": missing_fields,
            "warnings": warnings,
            "earnings_stability_pass": stability_pass,
            "earnings_growth_percent": round(growth_pct, 2) if growth_pct is not None else None,
            "graham_pe_pass": pe_pass,
            "graham_pb_pass": pb_pass,
            "graham_combined_pass": combined_pass,
            "current_ratio_pass": current_ratio >= config.min_current_ratio if current_ratio is not None else None,
            "long_term_debt_vs_working_capital_pass": lt_debt <= wc if (lt_debt is not None and wc is not None) else None,
            "graham_number": round(graham_number, 2) if graham_number is not None else None,
            "explanation": explanation
        }

    @classmethod
    async def get_fundamentals_report(cls, ticker_symbol: str, history_years: int = 10, include_raw: bool = False) -> FundamentalsResponse:
        """
        Fetch normalized metrics and perform defensive analysis.
        Return structured response schema model.
        """
        symbol = ticker_symbol.strip().upper()
        config = ScanConfig(eps_history_years=history_years)
        normalized = YahooFinanceClient.get_normalized_fundamentals(symbol)
        results = cls.analyze_ticker(normalized, config)
        eps_list = [YearlyEPS(year=y["year"], eps=round(y["eps"], 2)) for y in normalized.get("eps_history", [])]

        return FundamentalsResponse(
            ticker=normalized.get("ticker", symbol),
            company_name=normalized.get("company_name"),
            sector=normalized.get("sector"),
            industry=normalized.get("industry"),
            currency=normalized.get("currency"),
            market_cap=normalized.get("market_cap"),
            current_price=normalized.get("current_price"),
            trailing_pe=normalized.get("trailing_pe"),
            forward_pe=normalized.get("forward_pe"),
            price_to_book=normalized.get("price_to_book"),
            current_ratio=normalized.get("current_ratio"),
            debt_to_equity=normalized.get("debt_to_equity"),
            total_current_assets=normalized.get("total_current_assets"),
            total_current_liabilities=normalized.get("total_current_liabilities"),
            working_capital=normalized.get("working_capital"),
            long_term_debt=normalized.get("long_term_debt"),
            cash_and_equivalents=normalized.get("cash_and_equivalents"),
            operating_cash_flow=normalized.get("operating_cash_flow"),
            free_cash_flow=normalized.get("free_cash_flow"),
            roe=normalized.get("roe"),
            dividend_yield=normalized.get("dividend_yield"),
            dividend_rate=normalized.get("dividend_rate"),
            dividend_paying=normalized.get("dividend_paying", False),
            eps_history=eps_list,
            earnings_stability_pass=results["earnings_stability_pass"],
            earnings_growth_percent=results["earnings_growth_percent"],
            graham_pe_pass=results["graham_pe_pass"],
            graham_pb_pass=results["graham_pb_pass"],
            graham_combined_pass=results["graham_combined_pass"],
            long_term_debt_vs_working_capital_pass=results["long_term_debt_vs_working_capital_pass"],
            current_ratio_pass=results["current_ratio_pass"],
            graham_summary_score=results["score"],
            graham_summary_label=results["label"],
            graham_number=results["graham_number"],
            explanation=results["explanation"],
            missing_fields=results["missing_fields"],
            warnings=results["warnings"],
            raw_data=normalized["_raw_info"] if include_raw else None
        )
