# NSE 100-Bagger Stock Scanner

A production-grade quantitative FastAPI service designed to scan and rank NSE-listed equities based on **Christopher Mayer's 100-bagger principles** (as detailed in his book *"100 Baggers: Stocks That Made 100-to-1 and How to Find Them"*).

---

## 📈 Christopher Mayer's 100-Bagger Rules

The service normalizes and evaluates Yahoo Finance data using an evaluable checks points-based scoring system:

1.  **Starting Size (Weight 20)**: Median market cap of 100-baggers at the start is typically under $500M (equivalent to under 4,000 Crore INR).
2.  **Sales Growth (Weight 15)**: Multi-year sales revenue compound growth (CAGR >= 15%). Mayer stresses that sales growth is the primary engine.
3.  **EPS Growth (Weight 10)**: Multi-year EPS compound growth (CAGR >= 15%).
4.  **Capital Return Efficiency (Weight 20)**: Consistent Return on Equity (ROE >= 15%) indicating compound reinvestment efficiency.
5.  **Operating Moat (Weight 15)**: Operating Margin (>= 10%) indicating pricing power.
6.  **Valuation Room (Weight 5)**: Trailing P/E <= 40 to allow multiple expansion.
7.  **Insider Ownership (Weight 5)**: Skin in the game (promoter holding >= 30% in India).
8.  **Debt Safety (Weight 10)**: Low leverage (Debt-to-Equity <= 1.0) to survive cycles.

---

## 🚀 Getting Started

### 1. Install Dependencies
Navigate to the directory and install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Run the Server
Start the Uvicorn ASGI server:
```bash
python main.py
```
Or:
```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

---

## 📡 API Documentation & Examples

Endpoints require the `X-API-KEY` header credential:
*   Header Name: `X-API-KEY`
*   Header Value: `bagger_secret_api_key_2026`

### 1. GET `/health`
Diagnostics health check.

### 2. GET `/tickers`
Downloads and parses the active equity registry directly from the National Stock Exchange of India (NSE).
```bash
curl -X GET "http://localhost:8001/tickers" \
     -H "X-API-KEY: bagger_secret_api_key_2026"
```

### 3. POST `/scan`
Accepts a list of symbols and configuration overrides, returning ranked candidates sorted by potential score. If the `tickers` array is empty, it automatically pulls the equity list from the NSE and auto-screens the first `auto_limit` companies.

#### Request Example:
```json
{
  "tickers": ["DELHIVERY.NS", "ZOMATO.NS", "JNJ", "KO"],
  "config": {
    "max_market_cap_inr": 50000000000.0,
    "min_revenue_cagr": 15.0,
    "min_roe": 15.0,
    "max_pe_ratio": 45.0,
    "min_pass_ratio": 0.8
  }
}
```

#### Response Example:
```json
{
  "summary": {
    "total_input": 4,
    "total_processed": 4,
    "total_passed": 1,
    "total_failed": 3,
    "total_insufficient_data": 0
  },
  "candidates": [
    {
      "ticker": "DELHIVERY.NS",
      "company_name": "Delhivery Limited",
      "passed": false,
      "score": 50.0,
      "pass_ratio": 0.5,
      "label": "Low Potential",
      "checks": [
        {
          "check_name": "Starting Size",
          "passed": true,
          "description": "Market Cap: 38000.30 Cr INR <= 5000.0 Cr INR",
          "weight": 20.0,
          "achieved_weight": 20.0
        }
      ],
      "missing_fields": [],
      "warnings": [],
      "metrics": {
        "market_cap": 380002989665.0,
        "current_price": 507.45,
        "trailing_pe": 256.29,
        "roe": -3.52,
        "operating_margin": -2.48,
        "debt_to_equity": 0.05,
        "promoter_holding": 35.0,
        "revenue_cagr": 63.5
      },
      "explanation": "Delhivery Limited (DELHIVERY.NS) evaluated on 4/8 checks..."
    }
  ],
  "failed_candidates": ["ZOMATO.NS", "JNJ", "KO"],
  "insufficient_data_candidates": []
}
```
