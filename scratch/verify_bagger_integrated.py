import jwt
import time
import requests

# Generate valid JWT token
token = jwt.encode(
    {"sub": "default_user", "exp": int(time.time()) + 3600},
    "super_secret_key",
    algorithm="HS256"
)

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

base_url = "http://localhost:8000/api/v1/bagger"

print("=== Starting Integrated 100-Bagger API Verification ===")

# Start the uvicorn server in background or assume it's running.
# Since we are executing in Python, let's test using FastAPI TestClient to test synchronously!
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# 1. Test Auth Block
print("\n1. Testing Auth Block on /tickers...")
res = client.get("/api/v1/bagger/tickers")
print(f"No Auth Status: {res.status_code}, Response: {res.json()}")
assert res.status_code == 401

# 2. Test Get Tickers
print("\n2. Testing GET /tickers with auth...")
res = client.get("/api/v1/bagger/tickers", headers=headers)
print(f"Status: {res.status_code}")
assert res.status_code == 200
tickers = res.json()
print(f"Total active NSE tickers fetched: {len(tickers)}")
print(f"Sample tickers: {tickers[:10]}")
assert "DELHIVERY" in tickers

# 3. Test Scan Delhivery
print("\n3. Testing POST /scan for DELHIVERY.NS...")
payload = {
    "tickers": ["DELHIVERY.NS"],
    "config": {
        "max_market_cap_inr": 1000000000000.0, # relax cap size
        "min_revenue_cagr": 10.0,
        "min_roe": -10.0,
        "max_pe_ratio": 300.0,
        "min_pass_ratio": 0.5
    }
}
res = client.post("/api/v1/bagger/scan", json=payload, headers=headers)
print(f"Status: {res.status_code}")
assert res.status_code == 200
data = res.json()
print("Delhivery 100-Bagger scan results:")
print(f"  Summary: {data['summary']}")
cand = data["candidates"][0]
print(f"  Ticker: {cand['ticker']}")
print(f"  Company Name: {cand['company_name']}")
print(f"  Potential Score: {cand['score']}%")
print(f"  Label: {cand['label']}")
print("  Evaluations Checks:")
for check in cand["checks"]:
    print(f"    - {check['check_name']}: passed={check['passed']}, desc: {check['description']}")

# 4. Test Trigger Background Scan Job
print("\n4. Testing POST /trigger with auth...")
res = client.post("/api/v1/bagger/trigger?limit=3", headers=headers)
print(f"Status: {res.status_code}, Response: {res.json()}")
assert res.status_code == 202
assert "triggered successfully" in res.json()["message"]

# 5. Test Database-backed Scan with Default Filters (High & Moderate Potential only)
print("\n5. Testing DB-backed POST /scan with default filters...")
payload_db_filtered = {
    "tickers": [],
    "use_db": True,
    "filter_potentials": True
}
res = client.post("/api/v1/bagger/scan", json=payload_db_filtered, headers=headers)
print(f"Status: {res.status_code}")
assert res.status_code == 200
data = res.json()
print("Filtered Database candidates (Expected: only High Potential / Passed):")
for cand in data["candidates"]:
    print(f"  Ticker: {cand['ticker']}, Company: {cand['company_name']}, Label: {cand['label']}")
    assert cand["passed"] is True or cand["label"] == "High Potential"
print(f"Summary metrics: {data['summary']}")

# 6. Test Database-backed Scan without filters (show all)
print("\n6. Testing DB-backed POST /scan showing all candidates...")
payload_db_all = {
    "tickers": [],
    "use_db": True,
    "filter_potentials": False
}
res = client.post("/api/v1/bagger/scan", json=payload_db_all, headers=headers)
print(f"Status: {res.status_code}")
assert res.status_code == 200
data = res.json()
print("All Database candidates:")
for cand in data["candidates"]:
    print(f"  Ticker: {cand['ticker']}, Company: {cand['company_name']}, Label: {cand['label']}")
print(f"Summary metrics: {data['summary']}")

print("\nAll integrated 100-Bagger API checks passed successfully!")


