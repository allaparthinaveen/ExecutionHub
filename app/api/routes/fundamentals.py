import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Dict, Any, Tuple, Optional
from app.schemas.fundamentals import (
    FundamentalsResponse,
    ScanRequest,
    ScanResponse,
    ScreenerResult,
    ScanSummary
)
from app.services.fundamental_analyzer import FundamentalAnalyzer
from app.services.yahoo_client import YahooFinanceClient
from app.api.dependencies import get_current_user

logger = logging.getLogger("tradeservices.routes.fundamentals")
router = APIRouter()

@router.get("/getFundamentals", response_model=FundamentalsResponse)
async def get_fundamentals(
    ticker: str = Query(..., description="Stock ticker symbol (e.g. AAPL)"),
    history_years: int = Query(10, ge=1, le=20, description="History years to fetch EPS"),
    include_raw: bool = Query(False, description="Include raw ticker info in response"),
    user_id: str = Depends(get_current_user)
):
    """
    Fetch and normalize fundamental metrics for a single stock ticker.
    Applies Benjamin Graham's defensive checks and calculates scores.
    """
    try:
        report = await FundamentalAnalyzer.get_fundamentals_report(
            ticker_symbol=ticker,
            history_years=history_years,
            include_raw=include_raw
        )
        return report
    except Exception as e:
        logger.error(f"Error fetching fundamentals for {ticker}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch fundamentals for {ticker}: {str(e)}"
        )

async def _analyze_single_ticker_sem(
    symbol: str, 
    sem: asyncio.Semaphore, 
    config: Any
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """Helper method to run ticker analysis wrapped inside a concurrency semaphore."""
    async with sem:
        try:
            # yfinance operations are synchronous/blocking; run in executor to prevent event loop blocking
            loop = asyncio.get_event_loop()
            normalized = await loop.run_in_executor(
                None, YahooFinanceClient.get_normalized_fundamentals, symbol
            )
            analysis = FundamentalAnalyzer.analyze_ticker(normalized, config)
            return symbol, normalized, analysis, None
        except Exception as e:
            logger.error(f"Async scanning failed for ticker {symbol}: {e}")
            return symbol, None, None, str(e)

from typing import Tuple

@router.post("/scanFundamentallyStrong", response_model=ScanResponse)
async def scan_fundamentally_strong(
    request: ScanRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Deduplicate, sanitize, and scan a universe of tickers in parallel.
    Evaluate them against customizable Graham rules and return ranked results.
    """
    # 1. Deduplicate & sanitize inputs
    sanitized_tickers = sorted(list(set([t.strip().upper() for t in request.tickers if t.strip()])))
    if not sanitized_tickers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid tickers provided in request universe."
        )

    config = request.config
    sem = asyncio.Semaphore(config.max_concurrency)
    
    # 2. Concurrently execute queries
    tasks = [
        _analyze_single_ticker_sem(ticker, sem, config) 
        for ticker in sanitized_tickers
    ]
    
    raw_results = await asyncio.gather(*tasks)
    
    screener_results = []
    failed_candidates_list = []
    insufficient_data_list = []
    top_candidates_list = []
    
    total_processed = 0
    total_failed = 0
    total_insufficient = 0
    total_passed_count = 0
    
    # 3. Process results
    for symbol, normalized, analysis, err in raw_results:
        if err or normalized is None or analysis is None:
            total_failed += 1
            # Add a failing dummy result so we don't drop the ticker from response
            screener_results.append(
                ScreenerResult(
                    ticker=symbol,
                    passed=False,
                    score=0.0,
                    pass_ratio=0.0,
                    label="Weak",
                    reasons_passed=[],
                    reasons_failed=[f"Failed to fetch data from Yahoo Finance: {err or 'Unknown error'}"],
                    missing_fields=[],
                    warnings=[],
                    metrics={}
                )
            )
            failed_candidates_list.append(symbol)
            continue
            
        total_processed += 1
        
        # Build metrics dict for screener output
        metrics_dict = {
            "market_cap": normalized.get("market_cap"),
            "current_ratio": normalized.get("current_ratio"),
            "working_capital": normalized.get("working_capital"),
            "long_term_debt": normalized.get("long_term_debt"),
            "dividend_paying": normalized.get("dividend_paying"),
            "dividend_yield": normalized.get("dividend_yield"),
            "trailing_pe": normalized.get("trailing_pe"),
            "price_to_book": normalized.get("price_to_book"),
            "operating_cash_flow": normalized.get("operating_cash_flow"),
            "free_cash_flow": normalized.get("free_cash_flow"),
            "roe": normalized.get("roe"),
            "earnings_growth_percent": analysis.get("earnings_growth_percent"),
            "graham_number": analysis.get("graham_number")
        }
        
        result_item = ScreenerResult(
            ticker=symbol,
            company_name=normalized.get("company_name"),
            passed=analysis["passed"],
            score=analysis["score"],
            pass_ratio=analysis["pass_ratio"],
            label=analysis["label"],
            reasons_passed=analysis["reasons_passed"],
            reasons_failed=analysis["reasons_failed"],
            missing_fields=analysis["missing_fields"],
            warnings=analysis["warnings"],
            metrics=metrics_dict
        )
        
        screener_results.append(result_item)
        
        if analysis["label"] == "Insufficient Data":
            total_insufficient += 1
            insufficient_data_list.append(symbol)
        elif analysis["passed"]:
            total_passed_count += 1
            top_candidates_list.append(symbol)
        else:
            total_failed += 1
            failed_candidates_list.append(symbol)

    # 4. Sort results
    # Allowed fields: 'score', 'pass_ratio', 'market_cap'
    sort_key = request.sort_by.lower()
    if sort_key == "pass_ratio":
        screener_results.sort(key=lambda x: x.pass_ratio, reverse=request.descending)
    elif sort_key == "market_cap":
        screener_results.sort(key=lambda x: x.metrics.get("market_cap") or 0.0, reverse=request.descending)
    else:  # default 'score'
        screener_results.sort(key=lambda x: x.score, reverse=request.descending)
        
    # Apply limit
    screener_results = screener_results[:request.limit]
    
    summary = ScanSummary(
        total_input=len(sanitized_tickers),
        total_processed=total_processed,
        total_passed=total_passed_count,
        total_failed=total_failed,
        total_insufficient_data=total_insufficient
    )

    return ScanResponse(
        summary=summary,
        results=screener_results,
        top_candidates=top_candidates_list,
        failed_candidates=failed_candidates_list,
        insufficient_data_candidates=insufficient_data_list
    )
