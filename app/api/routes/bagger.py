import logging
import pandas as pd
import yfinance as yf
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Header
from typing import List, Optional
from sqlalchemy.orm import Session
from app.schemas.bagger import (
    ScanRequest,
    ScanResponse,
    ScanSummary,
    BaggerCandidate,
    ScreenerCheckResult,
    BacktestResponse,
    BacktestSummary,
    BacktestCandidateResult,
    YearlyMetric,
    StockMetrics
)
from app.services.bagger_scanner import BaggerScannerService
from app.api.dependencies import get_current_user, get_db
from app.models.trading import NSEBaggerScanResult

logger = logging.getLogger("tradeservices.routes.bagger")
router = APIRouter()

@router.get("/tickers", response_model=List[str])
def get_nse_tickers(user_id: str = Depends(get_current_user)):
    """
    Fetch the list of all active NSE listed equities symbols.
    Downloads the official EQ series list directly from NSE archives.
    """
    try:
        symbols = BaggerScannerService.fetch_nse_symbols()
        return symbols
    except Exception as e:
        logger.error(f"Error fetching active NSE symbols: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch active NSE symbols register: {str(e)}"
        )

@router.post("/scan", response_model=ScanResponse)
async def scan_tickers(
    request: ScanRequest,
    quantitative: Optional[str] = Header(None),
    qualitative: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    """
    Scan tickers for 100-bagger potential.
    
    If 'tickers' list is empty and 'use_db' is True:
      - Instantly queries the pre-computed database results table.
      - Returns sorted results in sub-milliseconds.
    Otherwise:
      - Runs a live crawl and scan engine check (parallel API queries).
    """
    tickers_list = request.tickers
    config = request.config
    
    # 1. Fast Database Read Path
    # 1. Fast Database Read Path
    if not tickers_list and request.use_db:
        logger.info(f"User {user_id} requested database scan read.")
        try:
            # Query pre-scanned records - filter strictly to passed == True by using score >= 90.0
            query = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.score >= 90.0)
            # Get raw records in database
            raw_records = query.all()
            
            candidates = []
            for record in raw_records:
                checks_list = []
                if record.checks:
                    for c in record.checks:
                        checks_list.append(
                            ScreenerCheckResult(
                                check_name=c.get("check_name", ""),
                                passed=c.get("passed", False),
                                description=c.get("description", ""),
                                weight=c.get("weight", 0.0),
                                achieved_weight=c.get("achieved_weight", 0.0)
                            )
                        )
                candidates.append(
                    BaggerCandidate(
                        ticker=record.ticker,
                        company_name=record.company_name,
                        passed=True, # Explicitly mark as True since we filter by score >= 90.0
                        score=record.score,
                        pass_ratio=record.pass_ratio,
                        label="High Potential",
                        checks=checks_list,
                        missing_fields=record.missing_fields or [],
                        warnings=record.warnings or [],
                        metrics=record.metrics or {},
                        explanation=record.explanation or ""
                    )
                )
                
            # Process, enrich, and sort candidates
            run_quant = (quantitative == "true")
            run_qual = (qualitative == "true")
            
            for c in candidates:
                m_dict = c.metrics or {}
                rev_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("revenue_history", [])]
                eps_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("eps_history", [])]
                roic_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("roic_history", [])]
                
                metrics = StockMetrics(
                    ticker=c.ticker,
                    company_name=c.company_name,
                    market_cap=m_dict.get("market_cap"),
                    current_price=m_dict.get("current_price"),
                    trailing_pe=m_dict.get("trailing_pe"),
                    forward_pe=m_dict.get("forward_pe"),
                    roe=m_dict.get("roe"),
                    operating_margin=m_dict.get("operating_margin"),
                    debt_to_equity=m_dict.get("debt_to_equity"),
                    promoter_holding=m_dict.get("promoter_holding"),
                    ocf_to_net_income_ratio=m_dict.get("ocf_to_net_income_ratio"),
                    pledged_percentage=m_dict.get("pledged_percentage", 0.0),
                    revenue_history=rev_hist,
                    eps_history=eps_hist,
                    roic_history=roic_hist
                )
                BaggerScannerService.enrich_candidate_qualitative_quantitative(c, metrics, run_quant, run_qual)
                
            if run_quant or run_qual:
                def get_enhanced_sort_key(c):
                    depri_key = 1 if not getattr(c, "deprioritized", False) else 0
                    comp_score = getattr(c, "composite_score", c.score) or c.score
                    promo = (c.metrics or {}).get("promoter_holding") or 0.0
                    roic_avg = (c.metrics or {}).get("roic_5y_avg") or 0.0
                    mcap = (c.metrics or {}).get("market_cap")
                    if mcap is None or mcap <= 0:
                        neg_mcap = -float('inf')
                    else:
                        neg_mcap = -mcap
                    return (depri_key, comp_score, promo, roic_avg, neg_mcap)
                candidates = sorted(candidates, key=get_enhanced_sort_key, reverse=True)
                candidates = candidates[:15]
            else:
                def get_default_sort_key(c):
                    mcap = (c.metrics or {}).get("market_cap")
                    if mcap is None or mcap < 500000000.0:
                        mcap = float('inf')
                    return (-c.score, mcap)
                candidates = sorted(candidates, key=get_default_sort_key)
                
            # Summary Metrics for database population (strictly aligned to 90% threshold)
            total_db_records = db.query(NSEBaggerScanResult).count()
            total_passed = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.score >= 90.0).count()
            total_failed = db.query(NSEBaggerScanResult).filter((NSEBaggerScanResult.score < 90.0) & (NSEBaggerScanResult.label != "Insufficient Data")).count()
            total_insufficient = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.label == "Insufficient Data").count()
            
            summary = ScanSummary(
                total_input=total_db_records,
                total_processed=total_db_records,
                total_passed=total_passed,
                total_failed=total_failed,
                total_insufficient_data=total_insufficient
            )
            
            return ScanResponse(
                summary=summary,
                candidates=candidates,
                failed_candidates=[],
                insufficient_data_candidates=[]
            )
        except Exception as db_err:
            logger.error(f"Database scan query failed: {db_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database query failed: {str(db_err)}"
            )
            
    # 2. Live Crawl / Scan Path
    # Handle auto-scan if tickers list is empty
    if not tickers_list:
        logger.info(f"Empty tickers list received; fetching active symbols registry to auto-limit {request.auto_limit} symbols.")
        try:
            full_list = BaggerScannerService.fetch_nse_symbols()
            tickers_list = full_list[:request.auto_limit]
        except Exception as e:
            logger.error(f"Failed to fetch NSE symbols list for auto-scan: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Auto-scan failed to retrieve active NSE symbols registry: {str(e)}"
            )
            
    if not tickers_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tickers provided and active NSE symbols registry is empty."
        )
 
    logger.info(f"Running live 100-bagger screening for {len(tickers_list)} symbols in parallel.")
    try:
        candidates, query_failures, failed_list, insufficient_list = await BaggerScannerService.scan_universe(
            tickers=tickers_list,
            config=config
        )
        
        # Calculate summary metrics
        total_passed = sum(1 for c in candidates if c.passed)
        total_processed = len(tickers_list) - len(query_failures)
        
        # Always filter candidates to passed ones only
        candidates = [c for c in candidates if c.passed]
        
        # Process, enrich, and sort candidates
        run_quant = (quantitative == "true")
        run_qual = (qualitative == "true")
        
        for c in candidates:
            m_dict = c.metrics or {}
            rev_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("revenue_history", [])]
            eps_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("eps_history", [])]
            roic_hist = [YearlyMetric(year=item["year"], value=item["value"]) for item in m_dict.get("roic_history", [])]
            
            metrics = StockMetrics(
                ticker=c.ticker,
                company_name=c.company_name,
                market_cap=m_dict.get("market_cap"),
                current_price=m_dict.get("current_price"),
                trailing_pe=m_dict.get("trailing_pe"),
                forward_pe=m_dict.get("forward_pe"),
                roe=m_dict.get("roe"),
                operating_margin=m_dict.get("operating_margin"),
                debt_to_equity=m_dict.get("debt_to_equity"),
                promoter_holding=m_dict.get("promoter_holding"),
                ocf_to_net_income_ratio=m_dict.get("ocf_to_net_income_ratio"),
                pledged_percentage=m_dict.get("pledged_percentage", 0.0),
                revenue_history=rev_hist,
                eps_history=eps_hist,
                roic_history=roic_hist
            )
            BaggerScannerService.enrich_candidate_qualitative_quantitative(c, metrics, run_quant, run_qual)
            
        if run_quant or run_qual:
            def get_enhanced_sort_key(c):
                depri_key = 1 if not getattr(c, "deprioritized", False) else 0
                comp_score = getattr(c, "composite_score", c.score) or c.score
                promo = (c.metrics or {}).get("promoter_holding") or 0.0
                roic_avg = (c.metrics or {}).get("roic_5y_avg") or 0.0
                mcap = (c.metrics or {}).get("market_cap")
                if mcap is None or mcap <= 0:
                    neg_mcap = -float('inf')
                else:
                    neg_mcap = -mcap
                return (depri_key, comp_score, promo, roic_avg, neg_mcap)
            candidates = sorted(candidates, key=get_enhanced_sort_key, reverse=True)
            candidates = candidates[:15]
        else:
            def get_default_sort_key(c):
                mcap = (c.metrics or {}).get("market_cap")
                if mcap is None or mcap < 500000000.0:
                    mcap = float('inf')
                return (-c.score, mcap)
            candidates = sorted(candidates, key=get_default_sort_key)
            
        summary = ScanSummary(
            total_input=len(tickers_list),
            total_processed=total_processed,
            total_passed=total_passed,
            total_failed=len(failed_list),
            total_insufficient_data=len(insufficient_list)
        )
        
        return ScanResponse(
            summary=summary,
            candidates=candidates,
            failed_candidates=failed_list + query_failures,
            insufficient_data_candidates=insufficient_list
        )
    except Exception as e:
        logger.error(f"100-bagger scanning execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rule engine scanning execution encountered a fatal error: {str(e)}"
        )

@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan_job(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = None,
    user_id: str = Depends(get_current_user)
):
    """
    Trigger the daily background 100-bagger scanning job.
    Runs asynchronously using FastAPI BackgroundTasks to prevent HTTP timeouts.
    """
    logger.info(f"User {user_id} triggered background scan job with limit={limit}.")
    background_tasks.add_task(
        BaggerScannerService.run_background_scan,
        limit=limit
    )
    return {"message": "Background scanning job triggered successfully. View console logs for details."}

@router.get("/backtest", response_model=BacktestResponse)
async def run_portfolio_backtest(
    start_year: int = 2022,
    total_investment: float = 50000.0,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    """
    Backtest the High Potential candidates currently stored in the database.
    
    Simulates investing a fixed amount (default: ₹50,000) split equally among
    all passed candidates starting at the specified start year, and calculates
    individual and overall annualized returns (CAGR) and final valuations.
    """
    logger.info(f"User {user_id} requested portfolio backtest starting from {start_year} (investment: {total_investment}).")
    
    # 1. Fetch High Potential candidates (passed candidates)
    records = db.query(NSEBaggerScanResult).filter(
        (NSEBaggerScanResult.passed == True) | (NSEBaggerScanResult.label == "High Potential")
    ).all()
    
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No High Potential candidates found in the database. Please run a scan job first to populate results."
        )
        
    tickers = [r.ticker for r in records]
    ticker_metadata = {r.ticker: {"name": r.company_name, "score": r.score} for r in records}
    
    # 2. Bulk download historical prices for start year and current prices
    logger.info(f"Downloading bulk price data from yfinance for {len(tickers)} tickers...")
    try:
        hist_data = yf.download(tickers=tickers, start=f"{start_year}-01-01", end=f"{start_year}-12-31")['Close']
        current_data = yf.download(tickers=tickers, period="5d")['Close']
    except Exception as e:
        logger.error(f"Failed to fetch bulk price data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve price history from Yahoo Finance: {str(e)}"
        )
        
    candidates_results = []
    allocation_per_stock = total_investment / len(tickers)
    years_elapsed = datetime.now().year - start_year
    if years_elapsed <= 0:
        years_elapsed = 1
        
    for ticker in tickers:
        name = ticker_metadata[ticker]["name"] or ticker
        
        # Calculate price then
        price_then = None
        if isinstance(hist_data, pd.DataFrame):
            if ticker in hist_data.columns:
                price_then = hist_data[ticker].dropna().mean()
        else:
            price_then = hist_data.dropna().mean()
            
        # Calculate price now
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
            logger.warning(f"Missing price data for {ticker}. Skipping from portfolio calculations.")
            continue
            
        multiple = price_now / price_then
        cagr = (multiple ** (1.0 / years_elapsed) - 1.0) * 100.0
        final_val = allocation_per_stock * multiple
        profit = final_val - allocation_per_stock
        
        candidates_results.append(
            BacktestCandidateResult(
                ticker=ticker,
                company_name=name,
                buy_price=round(float(price_then), 2),
                current_price=round(float(price_now), 2),
                multiple=round(float(multiple), 2),
                cagr=round(float(cagr), 2),
                allocated_amount=round(float(allocation_per_stock), 2),
                final_value=round(float(final_val), 2),
                profit=round(float(profit), 2)
            )
        )
        
    if not candidates_results:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve price data for any of the High Potential candidates."
        )
        
    total_final_value = sum(c.final_value for c in candidates_results)
    total_profit = total_final_value - total_investment
    overall_multiple = total_final_value / total_investment
    overall_cagr = (overall_multiple ** (1.0 / years_elapsed) - 1.0) * 100.0
    
    summary = BacktestSummary(
        total_candidates=len(candidates_results),
        total_investment=round(total_investment, 2),
        final_value=round(total_final_value, 2),
        total_profit=round(total_profit, 2),
        return_multiple=round(overall_multiple, 2),
        cagr=round(overall_cagr, 2)
    )
    
    return BacktestResponse(
        summary=summary,
        candidates=candidates_results
    )
