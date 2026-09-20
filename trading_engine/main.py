import asyncio
import json
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import websockets
import structlog

# Add src to Python path
sys.path.append(str(Path(__file__).parent / "src"))

from trading_engine.config.settings import settings
from trading_engine.brokers.adapters.binance import BinanceFuturesAdapter
from trading_engine.persistence.json_store import JSONStateStore
from trading_engine.policies.samurai import SamuraiTrailingPolicy
from trading_engine.core.engine import TrailingEngine
from trading_engine.models.market import MarketState
from trading_engine.observability.logging import setup_logging

# Initialize Logging
setup_logging(json_format=False, log_level="INFO")
logger = structlog.get_logger("trading_engine.main")

async def binance_ws_loop(engine: TrailingEngine, symbol: str):
    """
    Connects to Binance Futures WebSocket and streams mark prices to the engine.
    """
    ws_url = "wss://stream.binancefuture.com/ws" if settings.binance_testnet else "wss://fstream.binance.com/ws"
    stream_name = f"{symbol.lower()}@markPrice"
    
    # We also need basic symbol info for MarketState. We can fetch once using the adapter.
    # In a full system, you might have a dedicated MarketData provider updating ATR and tick size.
    adapter = engine.broker
    price_dp, qty_dp = adapter._load_tick_and_step()
    tick_size = Decimal('10') ** -price_dp
    
    logger.info("WEBSOCKET_STARTING", url=ws_url, stream=stream_name, tick_size=str(tick_size))
    
    while True:
        try:
            async with websockets.connect(f"{ws_url}/{stream_name}") as ws:
                logger.info("WEBSOCKET_CONNECTED")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    
                    # Expected Mark Price Stream Format:
                    # {"e":"markPriceUpdate","E":1562305380000,"s":"BTCUSDT","p":"11185.87785636","P":"11182.00000000","i":"11176.49500000","r":"0.00010000","T":1562305380000}
                    
                    if "p" in data:
                        mark_price = Decimal(data["p"])
                        # Build MarketState
                        market = MarketState(
                            symbol=symbol,
                            bid=mark_price, # Simplified: using mark price for both to avoid false liquidations
                            ask=mark_price,
                            last=mark_price,
                            spread=Decimal('0'),
                            timestamp=datetime.utcfromtimestamp(data["E"] / 1000.0),
                            tick_size=tick_size,
                            point_size=tick_size,
                            min_stop_distance=tick_size * 5  # Example minimum
                        )
                        
                        # Process ticks against all open positions in the engine
                        # (Normally we would only fetch open positions, but for this loop we get them all)
                        positions = engine.broker.get_positions()
                        for p in positions:
                            # Sync the position to the store so the engine knows it exists
                            existing = engine.store.get_position(p.position_id)
                            if not existing:
                                logger.info("NEW_POSITION_DETECTED", position_id=p.position_id, side=p.side.value, qty=str(p.quantity), entry=str(p.entry_price))
                                engine.store.save_position(p)
                            
                            # Fire the engine!
                            engine.process_tick(p.position_id, market)

        except websockets.ConnectionClosed:
            logger.warning("WEBSOCKET_DISCONNECTED", reason="Connection closed, retrying in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error("WEBSOCKET_ERROR", error=str(e), exc_info=True)
            await asyncio.sleep(5)

async def main():
    logger.info("STARTING_TRADING_ENGINE", env="TESTNET" if settings.binance_testnet else "LIVE")
    
    # 1. Initialize dependencies
    broker = BinanceFuturesAdapter()
    store = JSONStateStore()
    
    # 2. Check Broker Health
    if not broker.health_check():
        logger.error("BROKER_HEALTH_CHECK_FAILED", reason="Cannot connect to Binance or invalid API keys")
        return
        
    logger.info("BROKER_HEALTHY")
    
    # 3. Configure the Samurai Policy
    # We use the parameters identified during the forensic phase
    policy = SamuraiTrailingPolicy(activation_pts=Decimal('0.50'), step_pts=Decimal('0.20'))
    
    # 4. Initialize Engine
    engine = TrailingEngine(broker=broker, store=store, policy=policy)
    
    # 5. Start the WebSocket loop
    await binance_ws_loop(engine, settings.symbol)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("SHUTTING_DOWN")
