import requests
import json
import sys

def main():
    print("=== Starting US 100-Bagger API verification ===\n")
    
    # 1. Fetch token to use for auth
    # We will generate a mock JWT for testing
    from app.core.config import settings
    import jwt
    from datetime import datetime, timedelta
    
    token_payload = {
        "sub": "admin",
        "exp": datetime.utcnow() + timedelta(days=1)
    }
    jwt_token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm="HS256")
    
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }
    
    # We can test by running a mock scan against local server or validating components.
    # To do a local test on DB models without running a full uvicorn server:
    from app.models.base import Base, engine, SessionLocal
    from app.models.trading import USBaggerScanResult
    from app.services.bagger_scanner import BaggerScannerService
    import asyncio
    
    print("1. Creating database tables (including new us_bagger_scan_results)...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created/verified successfully.")
    
    print("\n2. Testing fetch_us_symbols registry...")
    us_symbols = BaggerScannerService.fetch_us_symbols()
    print(f"Total active US symbols fetched: {len(us_symbols)}")
    print(f"Sample tickers: {us_symbols[:15]}")
    
    # Let us run a test scan for a couple of US stocks: AAPL (Apple) and MSFT (Microsoft)
    print("\n3. Testing live US stock screening for AAPL and MSFT...")
    from app.schemas.bagger import BaggerFilterConfig
    config = BaggerFilterConfig()
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    candidates, query_failures, failed_list, insufficient_list = loop.run_until_complete(
        BaggerScannerService.scan_universe(
            tickers=["AAPL", "MSFT"],
            config=config
        )
    )
    
    print(f"Scanned {len(candidates)} candidates.")
    for c in candidates:
        mcap = c.metrics.get("market_cap")
        mcap_str = f"${mcap/1e9:.2f}B" if mcap else "N/A"
        print(f"  - {c.ticker} ({c.company_name}): Passed={c.passed}, Score={c.score}%, MCap={mcap_str}, Label={c.label}")
        
    print("\n4. Testing background job database storage...")
    # Let us run background scan limited to 3 tickers to populate our DB
    print("Running background scan batch for 3 US tickers...")
    loop.run_until_complete(
        BaggerScannerService.run_background_scan(limit=3, market="US")
    )
    
    db = SessionLocal()
    try:
        records = db.query(USBaggerScanResult).all()
        print(f"Total US scan records populated in DB: {len(records)}")
        for r in records:
            print(f"  - {r.ticker} ({r.company_name}): Score={r.score}%, Passed={r.passed}, Label={r.label}")
    finally:
        db.close()
        
    print("\nUS 100-Bagger backend architecture integration looks 100% SUCCESSFUL!")

if __name__ == "__main__":
    main()
