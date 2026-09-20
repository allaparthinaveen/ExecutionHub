import sys
import pandas as pd
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import matplotlib.pyplot as plt

# Add src to python path so we can import our modules
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))

from trading_engine.research.samurai.loader import SamuraiTradeLoader
from trading_engine.research.samurai.cleaner import SamuraiTradeCleaner
from trading_engine.backtesting.replay import ReplayEngine
from trading_engine.policies.samurai import SamuraiTrailingPolicy
from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.models.enums import OrderSide, PositionStatus

def generate_synthetic_ticks(entry: Decimal, sl: Decimal, tp: Decimal, action: str):
    """
    Generates a synthetic price path.
    Since we know the trade closed at the SL, the max favorable excursion must have been 
    enough to trail the SL to its final spot, and then retraced to hit it.
    """
    ticks = []
    
    # 1. Start at entry
    ticks.append(entry)
    
    # 2. Push price in favorable direction to max excursion
    # The final SL was recorded. If it's a Buy, the trailing SL is below the price.
    # We assume max excursion was slightly beyond the final SL + step distance.
    if action == 'Buy':
        max_price = max(entry, sl + Decimal('0.50')) # Add 50 pips buffer
        # generate path up
        current = entry
        while current < max_price:
            current += Decimal('0.10')
            ticks.append(current)
            
        # 3. Retrace back down to hit the final SL
        current = max_price
        while current > sl - Decimal('0.10'):
            current -= Decimal('0.10')
            ticks.append(current)
            
    else: # Sell
        min_price = min(entry, sl - Decimal('0.50'))
        # generate path down
        current = entry
        while current > min_price:
            current -= Decimal('0.10')
            ticks.append(current)
            
        # 3. Retrace back up to hit the final SL
        current = min_price
        while current < sl + Decimal('0.10'):
            current += Decimal('0.10')
            ticks.append(current)
            
    return ticks

def main():
    data_path = Path(__file__).parent.parent / "data" / "statement.csv"
    loader = SamuraiTradeLoader(str(data_path))
    raw_df = loader.load()
    cleaner = SamuraiTradeCleaner()
    # We will run backtest on the anomalies, since they are the ones with trailing SLs!
    _, invalid_df = cleaner.clean(raw_df) 
    
    # Policy Params (Simulating Samurai: Activate at 50 pips, step 20 pips)
    policy = SamuraiTrailingPolicy(activation_pts=Decimal('0.50'), step_pts=Decimal('0.20'))
    
    results = []
    
    for idx, row in invalid_df.iterrows():
        action = str(row.get('Action', ''))
        entry = Decimal(str(row.get('Open Price', '0')))
        statement_sl = Decimal(str(row.get('SL', '0')))
        qty = Decimal(str(row.get('Lots', '1')))
        
        pos_id = f"trade_{idx}"
        pos = Position(
            position_id=pos_id,
            symbol="XAUUSD",
            side=OrderSide.BUY if action == "Buy" else OrderSide.SELL,
            quantity=qty,
            entry_price=entry,
            current_price=entry,
            highest_price_since_entry=entry,
            lowest_price_since_entry=entry,
            opened_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            broker="simulator",
            account_id_hash="test",
            status=PositionStatus.OPEN
        )
        
        engine = ReplayEngine(policy)
        engine.add_position(pos)
        
        ticks = generate_synthetic_ticks(entry, statement_sl, Decimal('0'), action)
        
        for t in ticks:
            market = MarketState(
                symbol="XAUUSD",
                bid=t, ask=t, last=t, spread=Decimal('0'),
                timestamp=datetime.utcnow(),
                tick_size=Decimal('0.01'),
                point_size=Decimal('0.01'),
                min_stop_distance=Decimal('0.10')
            )
            engine.process_tick(market)
            
        final_engine_sl = engine.positions[pos_id].current_stop_loss
        if final_engine_sl is None:
            final_engine_sl = Decimal('0')
            
        diff = abs(final_engine_sl - statement_sl)
        
        if diff == 0:
            status = "Exact Match"
        elif diff <= Decimal('0.50'):
            status = "Close Match (<50 pips)"
        else:
            status = "Deviation"
            
        results.append({
            "id": pos_id,
            "status": status,
            "engine_sl": final_engine_sl,
            "statement_sl": statement_sl
        })
        
    df_res = pd.DataFrame(results)
    
    # Generate Pie Chart
    status_counts = df_res['status'].value_counts()
    
    plt.figure(figsize=(8, 6))
    plt.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#4CAF50', '#FFC107', '#F44336'])
    plt.title('Backtest: Simulated Engine SL vs Statement SL')
    
    # Save to artifacts
    out_dir = Path('/Users/naveenallaparthi/.gemini/antigravity-ide/brain/9abc0743-dba3-4bed-8101-0bd29257f739')
    out_dir.mkdir(parents=True, exist_ok=True)
    chart_path = out_dir / "backtest_results.png"
    plt.savefig(chart_path)
    print(f"Chart saved to {chart_path}")
    print("\nSummary:")
    print(status_counts)

if __name__ == "__main__":
    main()
