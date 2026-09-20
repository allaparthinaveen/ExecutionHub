import sys
from pathlib import Path

# Add src to python path so we can import our modules
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))

from trading_engine.research.samurai.loader import SamuraiTradeLoader
from trading_engine.research.samurai.cleaner import SamuraiTradeCleaner
from trading_engine.research.samurai.report import SamuraiForensicReporter

def main():
    data_path = Path(__file__).parent.parent / "data" / "statement.csv"
    
    loader = SamuraiTradeLoader(str(data_path))
    raw_df = loader.load()
    
    if raw_df is None:
        print("Failed to load data.")
        return
        
    cleaner = SamuraiTradeCleaner()
    valid_df, invalid_df = cleaner.clean(raw_df)
    
    reporter = SamuraiForensicReporter(str(Path(__file__).parent.parent / "data" / "reports"))
    report_path = reporter.generate_data_quality_report(
        raw_df, 
        valid_df, 
        invalid_df, 
        cleaner.get_anomalies()
    )
    
    print(f"Report generated at: {report_path}")

if __name__ == "__main__":
    main()
