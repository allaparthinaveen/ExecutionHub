import logging
import math
import pandas as pd
from typing import List, Dict, Any, Optional
from cachetools import TTLCache
from app.schemas.valuation import (
    ScreenerCandidate,
    DiscountRateDetails,
    GrowthRateDetails,
    FCFFForecastYear,
    ValuationResponse
)
from app.services.yahoo_client import get_yf_ticker, YahooFinanceClient

rf_cache = TTLCache(maxsize=5, ttl=1800)

logger = logging.getLogger("tradeservices.valuation")

class ValuationService:
    @staticmethod
    def _fetch_clean_metric(info: Dict[str, Any], key: str, default: float) -> float:
        if not info:
            return default
        val = info.get(key)
        if val is None or math.isnan(val) if isinstance(val, float) else False:
            return default
        return float(val)

    @staticmethod
    def _get_risk_free_rate() -> float:
        """Fetch 10-year US Treasury yield (^TNX) as proxy for Risk-Free Rate."""
        if "yield" in rf_cache:
            return rf_cache["yield"]
        try:
            tnx = get_yf_ticker("^TNX")
            hist = tnx.history(period="1d")
            if not hist.empty:
                # Yield is returned as percentage, e.g. 4.25 meaning 4.25%
                val = float(hist['Close'].iloc[-1])
                if 0.0 < val < 20.0:
                    rf_rate = val / 100.0
                    rf_cache["yield"] = rf_rate
                    return rf_rate
        except Exception as e:
            logger.warning(f"Failed to fetch Risk-Free Rate from ^TNX: {e}. Falling back to default.")
        return 0.04  # Default 4%

    @classmethod
    async def screen_universe(cls, tickers: List[str], stage: str) -> List[ScreenerCandidate]:
        candidates = []
        for symbol in tickers:
            symbol = symbol.strip().upper()
            try:
                info = YahooFinanceClient.get_ticker_info(symbol)
                statements = YahooFinanceClient.get_ticker_statements(symbol)
                fin = statements["financials"]
                bs = statements["balance_sheet"]
                cf = statements["cashflow"]
                
                # Extract simple metrics
                beta = cls._fetch_clean_metric(info, 'beta', 1.0)
                
                # Fetch FCF Yield
                fcf = info.get('freeCashflow')
                mcap = info.get('marketCap')
                fcf_yield = 0.0
                if fcf and mcap and mcap > 0:
                    fcf_yield = float(fcf) / float(mcap)
                else:
                    # Fallback to cashflow statement
                    try:
                        if 'Free Cash Flow' in cf.index and not cf.empty:
                            fcf_val = cf.loc['Free Cash Flow'].iloc[0]
                            if mcap and mcap > 0:
                                fcf_yield = float(fcf_val) / float(mcap)
                    except Exception:
                        pass
                
                peg = cls._fetch_clean_metric(info, 'pegRatio', 2.0)
                
                # Debt to Equity
                debt_to_equity = info.get('debtToEquity')
                if debt_to_equity is not None:
                    # yfinance returns debtToEquity as a percentage (e.g. 79.54 meaning 79.54% / 0.7954 D/E ratio)
                    debt_to_equity = float(debt_to_equity) / 100.0
                else:
                    # Fallback to balance sheet
                    try:
                        total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
                        equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 1
                        if equity != 0:
                            debt_to_equity = float(total_debt) / float(equity)
                        else:
                            debt_to_equity = 0.5
                    except Exception:
                        debt_to_equity = 0.5
                
                revenue_growth = cls._fetch_clean_metric(info, 'revenueGrowth', 0.05)
                operating_margin = cls._fetch_clean_metric(info, 'operatingMargins', 0.10)
                
                # Compute operating margin trend
                margin_trend = 0.0
                try:
                    if 'Total Revenue' in fin.index and 'Operating Income' in fin.index:
                        revs = fin.loc['Total Revenue']
                        op_inc = fin.loc['Operating Income']
                        margins = []
                        for i in range(min(len(revs), 3)):
                            r = float(revs.iloc[i])
                            o = float(op_inc.iloc[i])
                            margins.append(o / r if r > 0 else 0)
                        
                        # Financials are returned most recent first, e.g. [2025, 2024, 2023]
                        # We want newest - oldest
                        if len(margins) >= 3:
                            margin_trend = (margins[0] - margins[2]) / 2.0
                        elif len(margins) == 2:
                            margin_trend = margins[0] - margins[1]
                except Exception:
                    pass

                # Scoring Based on Aswath Damodaran's Criteria
                score = 0.0
                if stage == 'young_growth':
                    # High revenue growth, high beta, low debt-to-equity, low/improving margins, low FCF (high reinvestment)
                    score += revenue_growth * 100.0
                    score += beta * 5.0
                    score -= debt_to_equity * 5.0
                    score += margin_trend * 20.0
                    score -= fcf_yield * 10.0
                elif stage == 'mature_value':
                    # Moderate revenue growth, low beta (close to 1), stable/high margins, high FCF yield, moderate debt
                    score += fcf_yield * 100.0
                    score += operating_margin * 50.0
                    score -= abs(beta - 1.0) * 15.0
                    # Moderate growth is good (e.g. 2% to 10%)
                    if 0.02 <= revenue_growth <= 0.12:
                        score += 15.0
                    else:
                        score -= abs(revenue_growth - 0.07) * 50.0
                    # Moderate debt is acceptable, too high is bad
                    if 0.2 <= debt_to_equity <= 1.2:
                        score += 10.0
                    else:
                        score -= abs(debt_to_equity - 0.7) * 5.0
                elif stage == 'declining_turnaround':
                    # Negative or flat growth, improving margins (turnaround), high D/E, cheap PEG or FCF yield
                    score -= revenue_growth * 50.0
                    score += margin_trend * 100.0
                    score += debt_to_equity * 5.0
                    score += fcf_yield * 20.0
                
                candidates.append(
                    ScreenerCandidate(
                        ticker=symbol,
                        beta=beta,
                        fcf_yield=fcf_yield,
                        peg=peg,
                        debt_to_equity=debt_to_equity,
                        revenue_growth=revenue_growth,
                        operating_margin=operating_margin,
                        margin_trend=margin_trend,
                        score=round(score, 4)
                    )
                )
            except Exception as e:
                logger.error(f"Error processing ticker {symbol} during screening: {e}")
                
        # Sort candidates by score descending
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    @classmethod
    async def calculate_intrinsic_value(cls, symbol: str, overrides: Dict[str, Any] = None) -> ValuationResponse:
        symbol = symbol.strip().upper()
        if overrides is None:
            overrides = {}
            
        info = YahooFinanceClient.get_ticker_info(symbol)
        statements = YahooFinanceClient.get_ticker_statements(symbol)
        fin = statements["financials"]
        bs = statements["balance_sheet"]
        cf = statements["cashflow"]
        
        # 1. Pull dynamic inputs / statements
        current_price = cls._fetch_clean_metric(info, 'currentPrice', 100.0)
        shares_outstanding = cls._fetch_clean_metric(info, 'sharesOutstanding', 1.0e6)
        
        # 2. Part 1: Discount Rate (WACC) via CAPM
        rf = overrides.get('risk_free_rate_override')
        if rf is None:
            rf = cls._get_risk_free_rate()
            
        erp = overrides.get('erp_override')
        if erp is None:
            erp = 0.050  # Default 5.0% Equity Risk Premium
            
        beta = cls._fetch_clean_metric(info, 'beta', 1.0)
        cost_of_equity = rf + beta * erp
        
        # Cost of Debt and Tax Rate
        tax_rate = overrides.get('tax_rate_override')
        if tax_rate is None:
            try:
                tax_provision = float(fin.loc['Tax Provision'].iloc[0]) if 'Tax Provision' in fin.index else 0.0
                pretax_income = float(fin.loc['Pretax Income'].iloc[0]) if 'Pretax Income' in fin.index else 0.0
                if pretax_income > 0 and tax_provision > 0:
                    tax_rate = min(0.35, max(0.0, tax_provision / pretax_income))
                else:
                    tax_rate = 0.21
            except Exception:
                tax_rate = 0.21
                
        cost_of_debt = overrides.get('cost_of_debt_override')
        if cost_of_debt is None:
            # Estimate from interest coverage
            try:
                ebit = float(fin.loc['EBIT'].iloc[0]) if 'EBIT' in fin.index else 0.0
                interest = float(fin.loc['Interest Expense'].iloc[0]) if 'Interest Expense' in fin.index else 0.0
                interest = abs(interest)
                if interest > 0 and ebit > 0:
                    icr = ebit / interest
                    # Spread based on ICR
                    if icr > 8.5:
                        spread = 0.0125
                    elif icr > 6.5:
                        spread = 0.015
                    elif icr > 4.5:
                        spread = 0.02
                    elif icr > 2.5:
                        spread = 0.035
                    else:
                        spread = 0.05
                else:
                    spread = 0.02
                cost_of_debt = rf + spread
            except Exception:
                cost_of_debt = rf + 0.02

        # Debt to Equity Weights
        debt_to_equity = info.get('debtToEquity')
        if debt_to_equity is not None:
            debt_to_equity = float(debt_to_equity) / 100.0
        else:
            try:
                total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0.0
                equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 1.0
                debt_to_equity = float(total_debt) / float(equity) if equity != 0 else 0.3
            except Exception:
                debt_to_equity = 0.3
        
        # Guardrails on D/E
        if debt_to_equity < 0:
            debt_to_equity = 0.0
            
        equity_weight = 1.0 / (1.0 + debt_to_equity)
        debt_weight = debt_to_equity / (1.0 + debt_to_equity)
        
        wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1.0 - tax_rate)
        wacc = max(0.05, wacc)  # Floor at 5% cost of capital
        
        # 3. Part 2: Growth Rate
        # A. Fundamental Reinvestment Rate & ROC
        ebit = 0.0
        if 'EBIT' in fin.index and not fin.empty:
            ebit = float(fin.loc['EBIT'].iloc[0])
            
        # Reinvestment rate
        try:
            capex = abs(cf.loc['Capital Expenditure'].iloc[0]) if 'Capital Expenditure' in cf.index else 0.0
            deprec = abs(cf.loc['Depreciation And Amortization'].iloc[0]) if 'Depreciation And Amortization' in cf.index else 0.0
            if deprec == 0 and 'Depreciation Amortization Depletion' in cf.index:
                deprec = abs(cf.loc['Depreciation Amortization Depletion'].iloc[0])
            change_wc = cf.loc['Change In Working Capital'].iloc[0] if 'Change In Working Capital' in cf.index else 0.0
            
            reinvestment = capex - deprec + change_wc
            net_income_tax_adj = ebit * (1.0 - tax_rate)
            if net_income_tax_adj > 0:
                reinvestment_rate = max(0.1, min(0.9, reinvestment / net_income_tax_adj))
            else:
                reinvestment_rate = 0.40  # 40% default reinvestment
        except Exception:
            reinvestment_rate = 0.40
            
        # ROC (Return on Capital)
        try:
            total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0.0
            equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 1.0
            cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0.0
            invested_capital = equity + total_debt - cash
            if invested_capital > 0:
                roc = max(0.01, min(0.35, ebit * (1.0 - tax_rate) / invested_capital))
            else:
                roc = 0.12  # 12% default ROC
        except Exception:
            roc = 0.12
            
        fundamental_growth_rate = roc * reinvestment_rate
        
        # B. Historical Revenue CAGR
        historical_revenue_cagr = 0.05
        try:
            if 'Total Revenue' in fin.index and len(fin.loc['Total Revenue']) >= 2:
                revs = fin.loc['Total Revenue']
                latest_rev = float(revs.iloc[0])
                earliest_rev = float(revs.iloc[-1])
                years = len(revs) - 1
                if earliest_rev > 0 and latest_rev > 0:
                    historical_revenue_cagr = (latest_rev / earliest_rev) ** (1.0 / years) - 1.0
                    historical_revenue_cagr = max(-0.15, min(0.35, historical_revenue_cagr))
        except Exception:
            pass
            
        # Selected growth rate (Blended or Override)
        g = overrides.get('growth_rate_override')
        if g is None:
            g = 0.5 * fundamental_growth_rate + 0.5 * historical_revenue_cagr
            g = max(0.02, min(0.20, g))  # Constrain between 2% and 20%
            
        # 4. Part 3: Cash Flow (FCFF) & DCF Projection
        # Base FCFF calculation
        try:
            fcff_0 = ebit * (1.0 - tax_rate) * (1.0 - reinvestment_rate)
            if fcff_0 <= 0:
                # If negative, fallback to FCF margin of Revenue (default 8%)
                rev_latest = float(fin.loc['Total Revenue'].iloc[0]) if 'Total Revenue' in fin.index else 1000.0
                fcff_0 = max(1.0, rev_latest * 0.08)
        except Exception:
            rev_latest = float(fin.loc['Total Revenue'].iloc[0]) if 'Total Revenue' in fin.index else 1000.0
            fcff_0 = rev_latest * 0.08

        # Years 1 to 5 Forecast
        forecast = []
        sum_pv_fcff = 0.0
        for y in range(1, 6):
            fcff_y = fcff_0 * ((1.0 + g) ** y)
            df_y = 1.0 / ((1.0 + wacc) ** y)
            pv_y = fcff_y * df_y
            sum_pv_fcff += pv_y
            forecast.append(
                FCFFForecastYear(
                    year=y,
                    fcff=round(fcff_y, 2),
                    discount_factor=round(df_y, 4),
                    present_value=round(pv_y, 2)
                )
            )
            
        # Stable Growth rate for terminal value (cannot exceed risk free rate and capped at 3%)
        g_n = overrides.get('stable_growth_rate_override')
        if g_n is None:
            g_n = min(0.03, rf)
            
        # Terminal Value
        # Safeguard: if WACC <= g_n, adjust WACC upward to avoid infinite/negative Terminal Value
        stable_wacc = wacc
        if stable_wacc <= g_n:
            stable_wacc = g_n + 0.02
            
        terminal_value = (forecast[-1].fcff * (1.0 + g_n)) / (stable_wacc - g_n)
        pv_terminal_value = terminal_value / ((1.0 + wacc) ** 5)
        
        enterprise_value = sum_pv_fcff + pv_terminal_value
        
        # Cash and Debt
        try:
            cash = float(bs.loc['Cash Cash Equivalents And Short Term Investments'].iloc[0]) if 'Cash Cash Equivalents And Short Term Investments' in bs.index else 0.0
            if cash == 0.0 and 'Cash And Cash Equivalents' in bs.index:
                cash = float(bs.loc['Cash And Cash Equivalents'].iloc[0])
        except Exception:
            cash = 0.0
            
        try:
            debt = float(bs.loc['Total Debt'].iloc[0]) if 'Total Debt' in bs.index else 0.0
        except Exception:
            debt = 0.0
            
        equity_value = enterprise_value + cash - debt
        
        # Share Valuation
        if shares_outstanding > 0:
            intrinsic_value = equity_value / shares_outstanding
        else:
            intrinsic_value = 0.0
            
        # Valuation Conclusion
        pct_diff = ((intrinsic_value - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
        if pct_diff > 10.0:
            conclusion = f"Undervalued by {pct_diff:.1f}% (Buy/Undervalued)"
        elif pct_diff < -10.0:
            conclusion = f"Overvalued by {-pct_diff:.1f}% (Sell/Overvalued)"
        else:
            conclusion = "Fairly valued (±10% range)"
            
        return ValuationResponse(
            ticker=symbol,
            current_price=round(current_price, 2),
            discount_rate_details=DiscountRateDetails(
                risk_free_rate=round(rf, 4),
                beta=round(beta, 3),
                equity_risk_premium=round(erp, 4),
                cost_of_equity=round(cost_of_equity, 4),
                cost_of_debt=round(cost_of_debt, 4),
                tax_rate=round(tax_rate, 4),
                debt_to_equity=round(debt_to_equity, 4),
                equity_weight=round(equity_weight, 4),
                debt_weight=round(debt_weight, 4),
                wacc=round(wacc, 4)
            ),
            growth_rate_details=GrowthRateDetails(
                roc=round(roc, 4),
                reinvestment_rate=round(reinvestment_rate, 4),
                fundamental_growth_rate=round(fundamental_growth_rate, 4),
                historical_revenue_cagr=round(historical_revenue_cagr, 4),
                selected_growth_rate=round(g, 4)
            ),
            forecast=forecast,
            terminal_value=round(terminal_value, 2),
            present_value_terminal_value=round(pv_terminal_value, 2),
            sum_pv_fcff=round(sum_pv_fcff, 2),
            enterprise_value=round(enterprise_value, 2),
            cash=round(cash, 2),
            debt=round(debt, 2),
            equity_value=round(equity_value, 2),
            shares_outstanding=round(shares_outstanding, 0),
            intrinsic_value=round(intrinsic_value, 2),
            valuation_conclusion=conclusion
        )
