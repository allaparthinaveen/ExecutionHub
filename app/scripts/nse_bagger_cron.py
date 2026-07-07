import os
import sys
import time
import asyncio
import logging

# Ensure project root is in search path
project_root = "/Users/naveenallaparthi/github/ExecutionHub"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.models.base import SessionLocal, engine, Base
from app.models.trading import NSEBaggerScanResult
from app.services.bagger_scanner import BaggerScannerService
from app.schemas.bagger import BaggerFilterConfig

# Create tables in PostgreSQL if they don't exist
print("Ensuring database tables exist...")
Base.metadata.create_all(bind=engine)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nse_bagger.cron")

async def run_daily_scan():
    logger.info("Starting Daily NSE 100-Bagger Scanning Job...")
    start_time = time.time()
    
    db = SessionLocal()
    try:
        # 1. Fetch NSE tickers
        logger.info("Fetching active symbols registry from NSE...")
        nse_symbols = BaggerScannerService.fetch_nse_symbols()
        
        # Support running a fast dry run via command line argument
        limit = None
        for arg in sys.argv:
            if arg.startswith("--limit="):
                try:
                    limit = int(arg.split("=")[1])
                except Exception:
                    pass
        if limit:
            logger.info(f"Limiting active scan list to top {limit} symbols for testing/validation.")
            nse_symbols = nse_symbols[:limit]
            
        logger.info(f"Total symbols to process: {len(nse_symbols)}")
        
        # 2. Setup config
        config = BaggerFilterConfig()
        
        # We process in batches of 10 symbols to maintain high performance while avoiding rate blocks
        batch_size = 10
        total_symbols = len(nse_symbols)
        logger.info(f"Scanning all {total_symbols} equities in batches of {batch_size}...")
        
        processed_count = 0
        success_count = 0
        
        for i in range(0, total_symbols, batch_size):
            batch = nse_symbols[i:i+batch_size]
            batch_tickers = [f"{sym}.NS" for sym in batch]
            
            logger.info(f"Processing batch {i//batch_size + 1}: {batch}...")
            
            try:
                # Run batch scan (fetches yfinance + Screener.in fallback in parallel)
                candidates, query_failures, failed_list, insufficient_list = await BaggerScannerService.scan_universe(
                    tickers=batch_tickers,
                    config=config
                )
                
                # 3. Upsert results into database
                for cand in candidates:
                    # Convert checklist items and details to json-serializable format
                    checks_json = [check.model_dump() for check in cand.checks]
                    
                    # Look up existing row
                    db_record = db.query(NSEBaggerScanResult).filter(NSEBaggerScanResult.ticker == cand.ticker).first()
                    
                    if db_record:
                        # Update existing row
                        db_record.company_name = cand.company_name
                        db_record.passed = cand.passed
                        db_record.score = cand.score
                        db_record.pass_ratio = cand.pass_ratio
                        db_record.label = cand.label
                        db_record.metrics = cand.metrics
                        db_record.checks = checks_json
                        db_record.warnings = cand.warnings
                        db_record.missing_fields = cand.missing_fields
                        db_record.explanation = cand.explanation
                    else:
                        # Create new row
                        new_record = NSEBaggerScanResult(
                            ticker=cand.ticker,
                            company_name=cand.company_name,
                            passed=cand.passed,
                            score=cand.score,
                            pass_ratio=cand.pass_ratio,
                            label=cand.label,
                            metrics=cand.metrics,
                            checks=checks_json,
                            warnings=cand.warnings,
                            missing_fields=cand.missing_fields,
                            explanation=cand.explanation
                        )
                        db.add(new_record)
                
                # Commit batch
                db.commit()
                processed_count += len(batch)
                success_count += (len(batch) - len(query_failures))
                
                logger.info(f"Batch completed. Cumulative processed: {processed_count}/{total_symbols}. Active success: {success_count}.")
                
                # Soft sleep between batches to preserve API rate-limits
                await asyncio.sleep(1.0)
                
            except Exception as batch_err:
                logger.error(f"Error executing batch starting at index {i}: {batch_err}")
                db.rollback()
                
        elapsed = time.time() - start_time
        logger.info(f"NSE 100-Bagger Scanning Job completed in {elapsed:.2f} seconds!")
        logger.info(f"Final Stats: Total processed: {processed_count}, Successfully evaluated: {success_count}")
        
    except Exception as e:
        logger.critical(f"Daily cron scanner crashed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_daily_scan())
