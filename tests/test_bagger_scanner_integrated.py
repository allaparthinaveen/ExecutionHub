import unittest
from app.schemas.bagger import BaggerFilterConfig, StockMetrics, YearlyMetric
from app.services.bagger_scanner import BaggerScannerService

class TestBaggerScannerIntegrated(unittest.TestCase):
    def setUp(self):
        self.config = BaggerFilterConfig()
        
        self.perfect_stock = StockMetrics(
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

        self.weak_stock = StockMetrics(
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

    def test_calculate_cagr(self):
        # 10 to 14.4 in 2 years is ((14.4/10)**0.5 - 1) = 20%
        history = [
            YearlyMetric(year=2022, value=10.0),
            YearlyMetric(year=2023, value=12.0),
            YearlyMetric(year=2024, value=14.4)
        ]
        cagr = BaggerScannerService._calculate_cagr(history)
        self.assertEqual(cagr, 20.0)
        
        # Single element history should return None
        self.assertIsNone(BaggerScannerService._calculate_cagr([YearlyMetric(year=2022, value=10.0)]))

    def test_evaluate_perfect_candidate(self):
        result = BaggerScannerService.evaluate_candidate(self.perfect_stock, self.config)
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 100.0)
        self.assertEqual(result.pass_ratio, 1.0)
        self.assertEqual(result.label, "High Potential")
        self.assertEqual(len(result.checks), 8)
        self.assertTrue(all(c.passed for c in result.checks))

    def test_evaluate_weak_candidate(self):
        result = BaggerScannerService.evaluate_candidate(self.weak_stock, self.config)
        self.assertFalse(result.passed)
        self.assertLess(result.score, 20.0)
        self.assertEqual(result.label, "Low Potential")
        self.assertTrue(all(not c.passed for c in result.checks))

if __name__ == "__main__":
    unittest.main()
