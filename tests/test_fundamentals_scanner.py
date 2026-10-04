import pytest
from app.schemas.fundamentals import ScanConfig
from app.services.fundamental_analyzer import FundamentalAnalyzer

@pytest.fixture
def base_config():
    return ScanConfig()

@pytest.fixture
def perfect_company():
    return {
        "ticker": "PRFCT",
        "company_name": "Perfect Company Inc.",
        "market_cap": 3_000_000_000,
        "current_ratio": 2.5,
        "total_current_assets": 500_000_000,
        "total_current_liabilities": 200_000_000,
        "working_capital": 300_000_000,
        "long_term_debt": 100_000_000,
        "dividend_paying": True,
        "dividend_yield": 0.03,
        "trailing_pe": 12.0,
        "price_to_book": 1.2,
        "operating_cash_flow": 200_000_000,
        "free_cash_flow": 150_000_000,
        "roe": 0.15,
        "current_price": 50.0,
        "shares_outstanding": 60_000_000,
        "stockholders_equity": 2_500_000_000,
        "eps_history": [
            {"year": 2021, "eps": 1.50},
            {"year": 2022, "eps": 1.70},
            {"year": 2023, "eps": 2.00},
            {"year": 2024, "eps": 2.50},
            {"year": 2025, "eps": 3.00}
        ]
    }

@pytest.fixture
def weak_company():
    return {
        "ticker": "WEAK",
        "company_name": "Weak Company Inc.",
        "market_cap": 1_500_000_000,          # Fails Size (< 2B)
        "current_ratio": 1.5,                 # Fails Current Ratio (< 2.0)
        "total_current_assets": 300_000_000,
        "total_current_liabilities": 200_000_000,
        "working_capital": 100_000_000,
        "long_term_debt": 250_000_000,        # Fails LT Debt vs WC ($250M > $100M)
        "dividend_paying": False,             # Fails Dividend Status
        "dividend_yield": None,
        "trailing_pe": 20.0,                  # Fails PE (> 15.0)
        "price_to_book": 2.5,                 # Fails PB (> 1.5)
        "operating_cash_flow": -10_000_000,
        "free_cash_flow": -20_000_000,
        "roe": -0.02,
        "eps_history": [
            {"year": 2021, "eps": 1.00},
            {"year": 2022, "eps": 0.50},
            {"year": 2023, "eps": -0.20},     # Fails Earnings Stability (negative EPS)
            {"year": 2024, "eps": 0.10},
            {"year": 2025, "eps": 0.40}       # Fails Growth (Recent 2.5 vs Older 7.5 average)
        ]
    }

def test_perfect_company_scores_100(perfect_company, base_config):
    result = FundamentalAnalyzer.analyze_ticker(perfect_company, base_config)
    assert result["passed"] is True
    assert result["score"] == 100.0
    assert result["pass_ratio"] == 1.0
    assert result["label"] == "Strong"
    assert len(result["reasons_passed"]) == 9
    assert len(result["reasons_failed"]) == 0
    assert result["graham_number"] is not None

def test_weak_company_fails_checks(weak_company, base_config):
    result = FundamentalAnalyzer.analyze_ticker(weak_company, base_config)
    assert result["passed"] is False
    assert result["score"] < 40.0
    assert result["label"] == "Weak"
    assert len(result["reasons_failed"]) > 5
    assert result["earnings_stability_pass"] is False
    assert result["graham_pe_pass"] is False
    assert result["graham_pb_pass"] is False
    assert result["graham_combined_pass"] is False
    assert result["current_ratio_pass"] is False
    assert result["long_term_debt_vs_working_capital_pass"] is False

def test_missing_fields_degrades_gracefully(perfect_company, base_config):
    # Remove price_to_book
    perfect_company["price_to_book"] = None
    result = FundamentalAnalyzer.analyze_ticker(perfect_company, base_config)
    
    # We should still be able to evaluate the rest (possible weight goes from 100 to 90 because PB and combined PE*PB are skipped)
    # Check that it lists priceToBook as missing and has warning
    assert "priceToBook" in result["missing_fields"]
    assert any("price to book" in w.lower() for w in result["warnings"])
    assert result["score"] == 100.0  # Remaining evaluable checks (WACC, size, liq, debt, etc.) still pass
    assert result["graham_pb_pass"] is None
    assert result["graham_combined_pass"] is None

def test_insufficient_data_label(perfect_company, base_config):
    # Strip almost all metrics
    empty_company = {
        "ticker": "EMPTY",
        "market_cap": 1_000_000_000,
        "eps_history": []
    }
    result = FundamentalAnalyzer.analyze_ticker(empty_company, base_config)
    assert result["label"] == "Insufficient Data"
    assert result["passed"] is False
