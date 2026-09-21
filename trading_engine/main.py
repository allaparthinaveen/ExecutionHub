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
from trading_engine.policies.btc_policy import BTCRegimeTrailingPolicy
from trading_engine.core.engine import TrailingEngine
from trading_engine.execution.signal_engine import SamuraiSignalEngine
from trading_engine.execution.btc_signal_engine import BTCSignalEngine
from trading_engine.execution.manager import OrderManager
from trading_engine.models.market import MarketState
from trading_engine.observability.logging import setup_logging
from trading_engine.observability.notifications import TelegramNotificationProvider

# Initialize Logging
setup_logging(json_format=False, log_level="INFO")
logger = structlog.get_logger("trading_engine.main")

async def heartbeat_loop(notifier: TelegramNotificationProvider, broker: BinanceFuturesAdapter):
    """Fires a health-check Telegram message every 15 minutes."""
    while True:
        await asyncio.sleep(15 * 60)  # 15 minutes
        is_alive = broker.health_check()
        status = "✅ Online" if is_alive else "❌ UNREACHABLE"
        msg = (
            f"🤖 <b>Samurai Engine Heartbeat</b>\n\n"
            f"Status: <b>{status}</b>\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        if is_alive:
            notifier.send_info(msg)
        else:
            notifier.send_critical(msg)
        logger.info("HEARTBEAT_SENT", broker_alive=is_alive)

from typing import Any

async def binance_ws_loop(engine: TrailingEngine, signal_engine: Any, order_manager: OrderManager, symbol: str):
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
                        
                        # 1. Signal Engine evaluates the tick for a new entry
                        signal, metadata = signal_engine.evaluate(market)
                        if signal:
                            # 2. Order Manager executes the entry
                            order_manager.execute_entry(signal, metadata)
                        
                        # 3. Trailing Engine manages existing positions
                        positions = engine.broker.get_positions()
                        for p in positions:
                            existing = engine.store.get_position(p.position_id)
                            if not existing:
                                logger.info("NEW_POSITION_DETECTED", position_id=p.position_id, side=p.side.value, qty=str(p.quantity), entry=str(p.entry_price))
                                engine.store.save_position(p)
                            
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
    samurai_policy = SamuraiTrailingPolicy(activation_pts=Decimal('0.50'), step_pts=Decimal('0.20'))
    
    # 3b. Configure BTC Policy
    btc_policy = BTCRegimeTrailingPolicy(
        target_r=Decimal('1.5'),
        move_be_at_r=Decimal('1.0'),
        trail_start_r=Decimal('1.0'),
        trail_atr_mult=Decimal('1.0'),
        stop_atr_mult=Decimal('1.5')
    )
    
    # 4. Initialize Notifier
    notifier = TelegramNotificationProvider()

    # 5. Initialize Execution Managers (inject notifier)
    # SAMURAI ENGINE (XAUUSDT)
    samurai_engine = TrailingEngine(broker=broker, store=store, policy=samurai_policy, notifier=notifier)
    samurai_signals = SamuraiSignalEngine()
    samurai_order_mgr = OrderManager(broker=broker, store=store, notifier=notifier)
    
    # BTC ENGINE (BTCUSDT)
    btc_engine = TrailingEngine(broker=broker, store=store, policy=btc_policy, notifier=notifier)
    btc_signals = BTCSignalEngine()
    btc_order_mgr = OrderManager(broker=broker, store=store, notifier=notifier)

    # 6. Startup notification
    notifier.send_info(
        f"🚀 <b>Trading Engines Started</b>\n\n"
        f"Mode: <b>{'TESTNET' if settings.binance_testnet else 'LIVE'}</b>\n"
        f"Engines: Samurai ({settings.symbol}), BTC Regime (BTCUSDT)\n"
        f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    # 7. Run WebSocket loops + heartbeat concurrently
    await asyncio.gather(
        binance_ws_loop(samurai_engine, samurai_signals, samurai_order_mgr, settings.symbol),
        binance_ws_loop(btc_engine, btc_signals, btc_order_mgr, "BTCUSDT"),
        heartbeat_loop(notifier, broker),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("SHUTTING_DOWN")
