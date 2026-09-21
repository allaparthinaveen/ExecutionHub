import structlog
from decimal import Decimal
from trading_engine.brokers.base import BrokerAdapter
from trading_engine.persistence.state_store import StateStore
from trading_engine.models.enums import OrderSide
from trading_engine.config.settings import settings

from trading_engine.observability.notifications import NotificationProvider

logger = structlog.get_logger("trading_engine.execution.manager")

class OrderManager:
    """
    Acts as the bridge between the Signal Engine (Entries) and the Broker API.
    Enforces risk limits before placing the market order.
    """
    def __init__(self, broker: BrokerAdapter, store: StateStore, notifier: NotificationProvider):
        self.broker = broker
        self.store = store
        self.notifier = notifier
        
    def execute_entry(self, side: OrderSide, metadata: dict = None) -> bool:
        metadata = metadata or {}
        # 1. Check Risk Limits
        open_positions = self.broker.get_positions()
        if len(open_positions) >= settings.max_positions:
            logger.warning("ENTRY_REJECTED", reason="MAX_POSITIONS_REACHED", current=len(open_positions))
            return False
            
        # 2. Execute Market Order
        qty = Decimal(str(settings.max_lots)) # For testnet, just using max_lots as the fixed qty.
        logger.info("EXECUTING_ENTRY", side=side.value, qty=str(qty))
        
        result = self.broker.open_position(side=side, quantity=qty)
        
        if result:
            logger.info("ENTRY_SUCCESSFUL")
            fill_price = result.get("avgPrice", "UNKNOWN")
            
            # Simple initial SL/TP estimation for notification
            if fill_price != "UNKNOWN":
                try:
                    price = float(fill_price)
                    
                    if "pending_stop" in metadata:
                        sl_val = float(metadata["pending_stop"])
                        tp_val = price + (price - sl_val) * float(metadata.get("target_r", 1.5)) if side == OrderSide.BUY else price - (sl_val - price) * float(metadata.get("target_r", 1.5))
                    else:
                        sl_val = price - 10 if side == OrderSide.BUY else price + 10
                        tp_val = price + 30 if side == OrderSide.BUY else price - 30
                        
                    details = f"Fill Price: {price:.2f}\nInitial SL: {sl_val:.2f}\nTarget (TP): {tp_val:.2f}"
                except ValueError:
                    details = f"Fill Price: {fill_price}"
            else:
                details = "Fill Price: Market"

            msg = f"⚔️ <b>Samurai Engine Entry</b>\n\nSide: <b>{side.name}</b>\nQuantity: {qty}\n{details}"
            self.notifier.send_info(msg)
            return True
        else:
            logger.error("ENTRY_FAILED")
            self.notifier.send_error(f"Failed to place {side.name} entry order.")
            return False
