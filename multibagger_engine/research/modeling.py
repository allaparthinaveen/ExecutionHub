import pandas as pd
import numpy as np

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

def train_and_analyze_model(winners_features_df, controls_features_df):
    """
    Trains a Random Forest classifier to distinguish between historical 
    winners and failed breakouts, extracting the mathematical feature importance.
    """
    print("Preparing dataset for Statistical Modeling...")
    
    if not SKLEARN_AVAILABLE:
        print("ERROR: scikit-learn is not installed. Please run 'pip install scikit-learn'.")
        return pd.DataFrame()
        
    # Label the datasets
    winners_features_df['Is_Winner'] = 1
    controls_features_df['Is_Winner'] = 0
    
    # Combine
    dataset = pd.concat([winners_features_df, controls_features_df], ignore_index=True)
    
    # Select features for the model (Dropping text columns, dates, and fundamentals with NaNs for the MVRD)
    # We rely heavily on the point-in-time technicals and RVOL
    feature_columns = [
        'Dist_52W_High_%', 
        'Dist_52W_Low_%', 
        '1M_Return_%', 
        '6M_Return_%', 
        '12M_Return_%', 
        'Volatility_1Y_%'
        # Note: RVOL is in the entries df, we need to merge it in if we want it, 
        # but let's stick to the core features calculated in feature_engineering for now.
    ]
    
    # Prepare X and y
    X = dataset[feature_columns].copy()
    y = dataset['Is_Winner'].copy()
    
    # Handle any NaNs (fill with median for simplicity in Phase 6)
    X = X.fillna(X.median())
    
    print(f"Training Random Forest on {len(X)} samples with {len(feature_columns)} features...")
    
    # Initialize Model
    # We use a shallow tree to prevent overfitting on small MVRD datasets and extract generalized rules
    rf_model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    
    rf_model.fit(X, y)
    
    # Extract Feature Importance
    importances = rf_model.feature_importances_
    
    importance_df = pd.DataFrame({
        'Feature': feature_columns,
        'Importance_Weight': importances
    }).sort_values(by='Importance_Weight', ascending=False)
    
    # Normalize to percentage
    importance_df['Importance_%'] = (importance_df['Importance_Weight'] * 100).round(2).astype(str) + '%'
    
    return importance_df[['Feature', 'Importance_%']]
