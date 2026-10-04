import os
import sys
import unittest
from fastapi.testclient import TestClient

# Add directory paths to python search path
workspace_path = "/Users/naveenallaparthi/github/ExecutionHub"
if workspace_path not in sys.path:
    sys.path.insert(0, workspace_path)
scanner_path = "/Users/naveenallaparthi/github/ExecutionHub/nse_100_bagger_scanner"
if scanner_path not in sys.path:
    sys.path.insert(0, scanner_path)

from nse_100_bagger_scanner.main import app, API_KEY_NAME, API_KEY_VALUE
from nse_100_bagger_scanner.models import (
    BaggerFilterConfig,
    StockMetrics,
    YearlyMetric
)
from nse_100_bagger_scanner.services import BaggerScannerService

class TestBaggerScanner(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {API_KEY_NAME: API_KEY_VALUE}

    def test_calculate_cagr(self):
        print("Testing CAGR calculation...")
        # 10 to 14.4 in 2 years is ((14.4/10)**0.5 - 1) = 20%
        history = [
            YearlyMetric(year=2022, value=10.0),
            YearlyMetric(year=2023, value=12.0),
            YearlyMetric(year=2024, value=14.4)
        ]
        cagr = BaggerScannerService._calculate_cagr(history)
        self.assertEqual(cagr, 20.0)
        
        # Single element history should return None
        single = [YearlyMetric(year=2022, value=10.0)]
        self.assertIsNone(BaggerScannerService._calculate_cagr(single))
        
        # Negative value should return None
        neg = [YearlyMetric(year=2022, value=-5.0), YearlyMetric(year=2023, value=10.0)]
        self.assertIsNone(BaggerScannerService._calculate_cagr(neg))

    def test_evaluate_perfect_candidate(self):
        print("Testing perfect candidate evaluation...")
        perfect_stock = StockMetrics(
            ticker="PRFCT.NS",
            company_name="Perfect Multiplier Inc.",
            market_cap=20000000000.0,       # 2000 Cr (< 5000 Cr max size: passed)
            current_price=150.0,
            trailing_pe=25.0,               # < 40 max PE: passed
            forward_pe=20.0,
            roe=22.0,                       # > 15% min ROE: passed
            operating_margin=18.0,          # > 10% min margin: passed
            debt_to_equity=0.2,             # < 1.0 max leverage: passed
            promoter_holding=45.0,          # > 30% promoter holding: passed
            revenue_history=[
                YearlyMetric(year=2022, value=100.0),
                YearlyMetric(year=2023, value=120.0),
                YearlyMetric(year=2024, value=144.0)  # 20% CAGR (> 15% min: passed)
            ],
            eps_history=[
                YearlyMetric(year=2022, value=5.0),
                YearlyMetric(year=2023, value=6.0),
                YearlyMetric(year=2024, value=7.2)    # 20% CAGR (> 15% min: passed)
            ]
        )
        config = BaggerFilterConfig()
        result = BaggerScannerService.evaluate_candidate(perfect_stock, config)
        
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 100.0)
        self.assertEqual(result.pass_ratio, 1.0)
        self.assertEqual(result.label, "High Potential")
        self.assertEqual(len(result.checks), 8)
        self.assertTrue(all(c.passed for c in result.checks))

    def test_evaluate_weak_candidate(self):
        print("Testing weak candidate evaluation...")
        weak_stock = StockMetrics(
            ticker="WEAK.NS",
            company_name="Struggling Bloated Corp.",
            market_cap=200000000000.0,      # 20,000 Cr (> 5000 Cr max size: failed)
            current_price=80.0,
            trailing_pe=55.0,               # > 40 max PE: failed
            forward_pe=50.0,
            roe=5.0,                        # < 15% min ROE: failed
            operating_margin=4.0,           # < 10% min margin: failed
            debt_to_equity=2.5,             # > 1.0 max leverage: failed
            promoter_holding=15.0,          # < 30% promoter holding: failed
            revenue_history=[
                YearlyMetric(year=2022, value=1000.0),
                YearlyMetric(year=2023, value=1020.0),
                YearlyMetric(year=2024, value=1040.0)  # ~2% CAGR (< 15% min: failed)
            ],
            eps_history=[
                YearlyMetric(year=2022, value=4.0),
                YearlyMetric(year=2023, value=3.8),
                YearlyMetric(year=2024, value=3.5)    # Negative growth (< 15% min: failed)
            ]
        )
        config = BaggerFilterConfig()
        result = BaggerScannerService.evaluate_candidate(weak_stock, config)
        
        self.assertFalse(result.passed)
        self.assertLess(result.score, 20.0)
        self.assertEqual(result.label, "Low Potential")
        self.assertTrue(all(not c.passed for c in result.checks))

    def test_api_routes_diagnostics_and_auth(self):
        print("Testing API routes & auth blockers...")
        # 1. Health
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "healthy")
        
        # 2. Tickers auth check
        res = self.client.get("/tickers")
        self.assertEqual(res.status_code, 401)
        
        res = self.client.get("/tickers", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        symbols = res.json()
        self.assertTrue(len(symbols) > 0)
        self.assertIn("RELIANCE", symbols)

    def test_api_routes_scan_live_ticker(self):
        print("Testing API POST /scan with Delhivery...")
        payload = {
            "tickers": ["DELHIVERY.NS"],
            "config": {
                "max_market_cap_inr": 1000000000000.0, # relax size to fit Delhivery (~38k Cr)
                "min_revenue_cagr": 10.0,
                "min_roe": -10.0,  # relax ROE since Delhivery is currently negative
                "max_pe_ratio": 300.0,
                "min_pass_ratio": 0.5
            }
        }
        res = self.client.post("/scan", json=payload, headers=self.headers)
        print(f"POST /scan Status: {res.status_code}")
        self.assertEqual(res.status_code, 200)
        
        data = res.json()
        self.assertEqual(data["summary"]["total_input"], 1)
        self.assertEqual(data["summary"]["total_processed"], 1)
        
        cand = data["candidates"][0]
        self.assertEqual(cand["ticker"], "DELHIVERY.NS")
        print("Delhivery potential score:", cand["score"], "label:", cand["label"])
        print("Reasons passed:", [c["description"] for c in cand["checks"] if c["passed"]])
        print("Reasons failed:", [c["description"] for c in cand["checks"] if not c["passed"]])

if __name__ == "__main__":
    unittest.main()
