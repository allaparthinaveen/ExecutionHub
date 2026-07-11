import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional
from sqlalchemy.orm import Session
from app.schemas.bagger import (
    ScanRequest,
    ScanResponse,
    ScanSummary,
    BaggerCandidate,
    ScreenerCheckResult
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
    if not tickers_list and request.use_db:
        logger.info(f"User {user_id} requested database scan read (filter_potentials={request.filter_potentials}).")
        try:
            # Query pre-scanned records
            query = db.query(NSEBaggerScanResult)
            if request.filter_potentials:
                query = query.filter(NSEBaggerScanResult.passed == True)
                
            records = query.order_by(NSEBaggerScanResult.score.desc()).all()
            
            candidates = []
            for record in records:
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
                        passed=record.passed,
                        score=record.score,
                        pass_ratio=record.pass_ratio,
                        label=record.label,
                        checks=checks_list,
                        missing_fields=record.missing_fields or [],
                        warnings=record.warnings or [],
                        metrics=record.metrics or {},
                        explanation=record.explanation or ""
                    )
                )
                
            # Summary Metrics for database population
            total_db_records = db.query(NSEBaggerScanResult).count()
            total_passed = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.label == "High Potential").count()
            total_failed = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.label == "Low Potential").count()
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
        
        # Filter candidates if filter_potentials is True
        if request.filter_potentials:
            candidates = [c for c in candidates if c.passed]
            
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
