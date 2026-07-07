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
        
        # Stats counters
        stocks_fetched = len(nse_symbols)
        stocks_scanned = 0
        stocks_updated = 0
        stocks_created = 0
        stocks_failed = 0
        
        # Qualitative Screening Counters
        stocks_high_potential = 0
        stocks_moderate_potential = 0
        stocks_low_potential = 0
        stocks_insufficient_data = 0
        
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
                    if cand.ticker in query_failures:
                        stocks_failed += 1
                        continue
                        
                    stocks_scanned += 1
                    
                    # Track qualitative screening results
                    if cand.label == "High Potential":
                        stocks_high_potential += 1
                    elif cand.label == "Moderate Potential":
                        stocks_moderate_potential += 1
                    elif cand.label == "Low Potential":
                        stocks_low_potential += 1
                    elif cand.label == "Insufficient Data":
                        stocks_insufficient_data += 1
                    
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
                        stocks_updated += 1
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
                        stocks_created += 1
                
                # Commit batch
                db.commit()
                
                logger.info(f"Batch completed. Cumulative processed: {stocks_scanned + stocks_failed}/{total_symbols}.")
                
                # Soft sleep between batches to preserve API rate-limits
                await asyncio.sleep(1.0)
                
            except Exception as batch_err:
                logger.error(f"Error executing batch starting at index {i}: {batch_err}")
                db.rollback()
                
        elapsed = time.time() - start_time
        
        # Performance speed calculations
        avg_speed_ms = round((elapsed * 1000) / stocks_scanned, 1) if stocks_scanned > 0 else 0.0
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        
        summary_msg = f"""
=============================SCAN SCHEDULAR SUMMARY START=========================
[Core Scan Statistics]
Number of stocks fetched - {stocks_fetched}
Number of stocks scanned - {stocks_scanned}
Number of stocks failed to scan - {stocks_failed}

[Database Operations]
Number of stocks updated in DB - {stocks_updated}
Number of stocks created in DB - {stocks_created}

[Quantitative Screening Results]
High Potential Candidates (Passed 100-Bagger) - {stocks_high_potential}
Moderate Potential Candidates - {stocks_moderate_potential}
Low Potential Candidates - {stocks_low_potential}
Insufficient Data Candidates (Skipped) - {stocks_insufficient_data}

[Data Diagnostics & Performance]
Total Elapsed Time - {time_str}
Average Scan Speed - {avg_speed_ms} ms/stock
=============================SCAN SCHEDULAR SUMMARY END=========================
"""
        print(summary_msg)
        logger.info(f"NSE 100-Bagger Scanning Job completed in {elapsed:.2f} seconds!")
        
    except Exception as e:
        logger.critical(f"Daily cron scanner crashed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_daily_scan())
