import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from multibagger_engine.data.universe import get_mvrd_universe
from multibagger_engine.data.prices import download_historical_prices
from multibagger_engine.research.winner_detection import calculate_rolling_returns, identify_multibagger_cohorts
from multibagger_engine.research.entry_detection import detect_run_starts
from multibagger_engine.features.feature_engineering import calculate_entry_features
from multibagger_engine.research.sector_analysis import fetch_market_index, analyze_market_regime
from multibagger_engine.research.control_matching import identify_control_group
from multibagger_engine.research.modeling import train_and_analyze_model

def run_phase_1():
    print("============================================================")
    print("PHASE 1: HISTORICAL UNIVERSE & MULTIBAGGER DETECTION")
    print("============================================================")
    
    # 1. Define Universe
    universe = get_mvrd_universe()
    print(f"Loaded universe of {len(universe)} symbols.")
    
    # 2. Download 10 years of data
    df = download_historical_prices(universe, period="10y", interval="1d")
    
    if df.empty:
        print("Error: No price data available.")
        return
        
    # 3. Calculate 3-Year Rolling Returns
    df_with_returns = calculate_rolling_returns(df, days=750)
    
    # 4. Identify Winners (e.g. 300% return = 3.0)
    winners = identify_multibagger_cohorts(df_with_returns, min_return=3.0)
    
    print("\nTop 15 Historical Multibagger Entry Points Identified:")
    print("============================================================")
    
    # Format nicely
    display_df = winners.head(15).copy()
    display_df['Return_%'] = (display_df['Forward_3Y_Return'] * 100).round(2).astype(str) + '%'
    print(display_df[['Date', 'Symbol', 'Close', 'Return_%']].to_string(index=False))

    print("\n============================================================")
    print("PHASE 2: RUN-START DETECTION")
    print("============================================================")
    
    # We want to find the technical run-start for all unique winners (top 15 for demo)
    entries = detect_run_starts(df, display_df)
    
    print("\nDetected Run-Starts for Top Winners:")
    print("============================================================")
    entries['RVOL_At_Entry'] = entries['RVOL_At_Entry'].round(2).astype(str) + 'x'
    entries['Optimal_3Y_Return_%'] = (entries['Optimal_3Y_Return'] * 100).round(2).astype(str) + '%'
    print(entries[['Run_Start_Date', 'Symbol', 'Run_Start_Price', 'RVOL_At_Entry', 'Optimal_3Y_Date', 'Optimal_3Y_Return_%']].to_string(index=False))

    print("\n============================================================")
    print("PHASE 3: QUANTITATIVE FEATURES AT ENTRY")
    print("============================================================")
    
    # Calculate point-in-time features for the detected entries
    features_df = calculate_entry_features(df, entries)
    
    print("\nPoint-In-Time Features Discovered for Winners:")
    print("============================================================")
    
    columns_to_show = ['Symbol', 'Entry_Date', 'Dist_52W_High_%', '12M_Return_%', 'Volatility_1Y_%', 'ROE_%', 'OperatingMargin_%']
    print(features_df[columns_to_show].to_string(index=False))

    print("\n============================================================")
    print("PHASE 4: MARKET REGIME & CATALYST ENGINE")
    print("============================================================")
    
    # Fetch Nifty 50
    nifty_df = fetch_market_index()
    
    # Analyze Regime
    regime_df = analyze_market_regime(features_df, nifty_df)
    
    print("\nMarket Condition at the EXACT time these stocks broke out:")
    print("============================================================")
    print(regime_df.to_string(index=False))

    print("\n============================================================")
    print("PHASE 5: WINNER VS CONTROL GROUP")
    print("============================================================")
    
    # 1. Identify control cases
    controls_df = identify_control_group(df_with_returns, entries)
    
    # We rename 'Run_Start_Date' to 'Entry_Date' to reuse calculate_entry_features
    controls_for_features = controls_df.rename(columns={'Run_Start_Date': 'Entry_Date'}).copy()
    controls_for_features['Run_Start_Date'] = controls_for_features['Entry_Date']
    
    # 2. Calculate their point-in-time features
    control_features_df = calculate_entry_features(df, controls_for_features)
    
    print("\nPoint-In-Time Features Discovered for CONTROLS (Failed Breakouts):")
    print("============================================================")
    print(control_features_df[columns_to_show].to_string(index=False))

    print("\n============================================================")
    print("PHASE 6: STATISTICAL MODELING (FEATURE IMPORTANCE)")
    print("============================================================")
    
    # Train Random Forest to find out what separates Winners from Controls
    importance_df = train_and_analyze_model(features_df, control_features_df)
    
    if not importance_df.empty:
        print("\nMathematical Feature Importance Rankings:")
        print("============================================================")
        print(importance_df.to_string(index=False))
        print("\nInterpretation: The model heavily weights the features with the highest %.")
        print("This proves which point-in-time metrics are most critical for a true multibagger.")

if __name__ == "__main__":
    run_phase_1()
