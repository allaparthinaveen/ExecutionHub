import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent / "trading_engine" / "src"))

from trading_engine.brokers.adapters.binance import BinanceFuturesAdapter

def main():
    broker = BinanceFuturesAdapter()
    print("Testing Daily High/Low Fetcher for XAUUSDT (Samurai)...")
    hl = broker.get_previous_daily_high_low("XAUUSDT")
    if hl:
        print(f"✅ Success! XAUUSDT Prev High: {hl[0]}, Low: {hl[1]}")
    else:
        print("❌ Failed to fetch XAUUSDT data.")
        
    print("\nTesting for BTCUSDT...")
    hl_btc = broker.get_previous_daily_high_low("BTCUSDT")
    if hl_btc:
        print(f"✅ Success! BTCUSDT Prev High: {hl_btc[0]}, Low: {hl_btc[1]}")
    else:
        print("❌ Failed to fetch BTCUSDT data.")

if __name__ == "__main__":
    main()
