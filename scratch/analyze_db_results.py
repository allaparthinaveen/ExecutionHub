import os
import sys
import json
import sqlite3

try:
    import psycopg2
except ImportError:
    psycopg2 = None

def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        if not psycopg2:
            print("ERROR: DATABASE_URL is set but 'psycopg2-binary' is not installed.")
            print("Run: pip install psycopg2-binary")
            sys.exit(1)
        # Parse connection string or connect directly
        # If the URL starts with postgres://, replace with postgresql:// for compatibility
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        print(f"Connecting to PostgreSQL database...")
        return psycopg2.connect(db_url)
    else:
        print("Connecting to local SQLite database: test_bagger_scan.db")
        return sqlite3.connect('test_bagger_scan.db')

def analyze():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Overall stats
    cursor.execute("SELECT label, count(*) FROM nse_bagger_scan_results GROUP BY label")
    stats = cursor.fetchall()
    print("\n=================== DATABASE OVERALL STATS ===================")
    for label, count in stats:
        print(f"{label}: {count}")
    print("==============================================================")
    
    # 2. High & Moderate Potential details
    cursor.execute("""
        SELECT ticker, company_name, score, label, metrics 
        FROM nse_bagger_scan_results 
        WHERE label IN ('High Potential', 'Moderate Potential')
        ORDER BY score DESC
    """)
    records = cursor.fetchall()
    print("\n================ HIGH & MODERATE POTENTIAL CANDIDATES ================")
    for ticker, name, score, label, metrics_str in records:
        print(f"\nTicker: {ticker}")
        print(f"Company: {name}")
        print(f"Score: {score}%")
        print(f"Classification: {label}")
        
        try:
            # PostgreSQL returns JSON columns as dicts, SQLite returns as string
            metrics = json.loads(metrics_str) if isinstance(metrics_str, str) else metrics_str
            if metrics:
                print("Metrics Summary:")
                mc = metrics.get('market_cap')
                if mc:
                    print(f"  - Market Cap: {mc/1e7:.2f} Cr INR")
                else:
                    print("  - Market Cap: None")
                print(f"  - Trailing PE: {metrics.get('trailing_pe')}")
                print(f"  - ROE: {metrics.get('roe')}%")
                print(f"  - Operating Margin: {metrics.get('operating_margin')}%")
                print(f"  - Debt/Equity: {metrics.get('debt_to_equity')}")
                print(f"  - Promoter Holding: {metrics.get('promoter_holding')}%")
                print(f"  - Sales CAGR (10Y): {metrics.get('revenue_cagr')}%")
                print(f"  - EPS CAGR (10Y): {metrics.get('eps_cagr')}%")
            else:
                print("  - No metrics available")
        except Exception as e:
            print(f"  - Error parsing metrics: {e}")
    print("=======================================================================")
    conn.close()

if __name__ == '__main__':
    analyze()
