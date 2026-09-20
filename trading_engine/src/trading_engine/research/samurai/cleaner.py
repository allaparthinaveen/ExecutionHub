import pandas as pd
import structlog
from typing import Tuple

logger = structlog.get_logger("trading_engine.research.samurai.cleaner")

class SamuraiTradeCleaner:
    def __init__(self):
        self.anomalies = []
        
    def clean(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Cleans the loaded dataframe.
        Returns (valid_records, invalid_records).
        """
        if df is None or df.empty:
            return pd.DataFrame(), pd.DataFrame()
            
        # Filter out deposits/withdrawals
        df_trades = df[df['Action'].isin(['Buy', 'Sell'])].copy()
        
        valid = []
        invalid = []
        
        for idx, row in df_trades.iterrows():
            is_valid = True
            reason = ""
            
            try:
                # Basic checks
                action = str(row.get('Action', ''))
                entry = float(row.get('Open Price', 0))
                sl = float(row.get('SL', 0))
                tp = float(row.get('TP', 0))
                
                if entry <= 0:
                    is_valid = False
                    reason = "Zero or negative entry price"
                elif action == 'Buy' and sl > 0 and sl >= entry:
                    is_valid = False
                    reason = f"Buy SL ({sl}) >= Entry ({entry})"
                elif action == 'Sell' and sl > 0 and sl <= entry:
                    is_valid = False
                    reason = f"Sell SL ({sl}) <= Entry ({entry})"
                    
            except Exception as e:
                is_valid = False
                reason = f"Parsing error: {str(e)}"
                
            if is_valid:
                valid.append(row)
            else:
                self.anomalies.append({
                    "record_id": idx,
                    "reason": reason,
                    "original_values": row.to_dict()
                })
                invalid.append(row)
                
        valid_df = pd.DataFrame(valid) if valid else pd.DataFrame(columns=df.columns)
        invalid_df = pd.DataFrame(invalid) if invalid else pd.DataFrame(columns=df.columns)
        
        logger.info("CLEANING_COMPLETE", total=len(df), valid=len(valid_df), invalid=len(invalid_df))
        return valid_df, invalid_df
        
    def get_anomalies(self) -> list:
        return self.anomalies
