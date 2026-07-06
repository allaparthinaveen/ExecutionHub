import logging
from fastapi import FastAPI, HTTPException, status, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from nse_100_bagger_scanner.models import (
    ScanRequest,
    ScanResponse,
    ScanSummary,
    BaggerFilterConfig
)
from nse_100_bagger_scanner.utils import fetch_nse_symbols
from nse_100_bagger_scanner.services import BaggerScannerService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nse_100_bagger.main")

app = FastAPI(
    title="NSE 100-Bagger Stock Scanner",
    description="Quantitative screening service based on Christopher Mayer's 100-bagger principles for NSE-listed equities.",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Simple API Key authentication dependency
API_KEY_NAME = "X-API-KEY"
API_KEY_VALUE = "bagger_secret_api_key_2026"

async def verify_api_key(x_api_key: Optional[str] = Header(None, alias=API_KEY_NAME)):
    """Simple API key authentication check."""
    if not x_api_key or x_api_key != API_KEY_VALUE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-KEY header credential."
        )
    return x_api_key

@app.get("/health", tags=["diagnostics"])
def health_check():
    """Diagnostic health check endpoint."""
    return {
        "status": "healthy",
        "service": "nse-100-bagger-scanner",
        "version": "1.0.0"
    }

@app.get("/tickers", response_model=List[str], tags=["data"])
def get_nse_tickers(authenticated: str = Depends(verify_api_key)):
    """Fetch the active equities list directly from the NSE website."""
    try:
        symbols = fetch_nse_symbols()
        return symbols
    except Exception as e:
        logger.error(f"Error fetching active NSE symbols list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch active NSE symbols register: {str(e)}"
        )

@app.post("/scan", response_model=ScanResponse, tags=["screener"])
async def scan_tickers(
    request: ScanRequest,
    authenticated: str = Depends(verify_api_key)
):
    """
    Sanitize and scan a universe of tickers in parallel.
    Evaluate them against Christopher Mayer checks and return ranked candidates.
    If 'tickers' list is empty, automatically crawls the top N symbols from the NSE register.
    """
    tickers_list = request.tickers
    config = request.config or BaggerFilterConfig()
    
    # 1. Handle auto-scan if tickers list is empty
    if not tickers_list:
        logger.info(f"Empty tickers list received; fetching active symbols registry to auto-limit {request.auto_limit} symbols.")
        try:
            full_list = fetch_nse_symbols()
            # Slice first N symbols to avoid excessive network load / timeouts
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

    # 2. Run rule engine scan
    logger.info(f"Running 100-bagger screening for {len(tickers_list)} symbols in parallel.")
    try:
        candidates, query_failures, failed_list, insufficient_list = await BaggerScannerService.scan_universe(
            tickers=tickers_list,
            config=config
        )
        
        # Calculate summary metrics
        total_passed = sum(1 for c in candidates if c.passed)
        # Delhivery was successfully processed (not a query failure)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
