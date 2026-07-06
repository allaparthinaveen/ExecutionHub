import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.schemas.bagger import (
    ScanRequest,
    ScanResponse,
    ScanSummary
)
from app.services.bagger_scanner import BaggerScannerService
from app.api.dependencies import get_current_user

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
    user_id: str = Depends(get_current_user)
):
    """
    Scan a list of tickers in parallel and filter candidates using
    Christopher Mayer's 100-bagger principles.
    If 'tickers' list is empty, automatically crawls the top N symbols from the NSE register.
    """
    tickers_list = request.tickers
    config = request.config
    
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

    logger.info(f"Running 100-bagger screening for {len(tickers_list)} symbols in parallel.")
    try:
        candidates, query_failures, failed_list, insufficient_list = await BaggerScannerService.scan_universe(
            tickers=tickers_list,
            config=config
        )
        
        # Calculate summary metrics
        total_passed = sum(1 for c in candidates if c.passed)
        total_processed = len(tickers_list) - len(query_failures)
        
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
