import hashlib
import hmac
import time
import requests
from typing import List, Optional, Tuple
from decimal import Decimal

import structlog
from trading_engine.brokers.base import BrokerAdapter
from trading_engine.models.position import Position
from trading_engine.models.enums import OrderSide, PositionStatus
from trading_engine.config.settings import settings

logger = structlog.get_logger("trading_engine.broker.binance")

class BinanceFuturesAdapter(BrokerAdapter):
    """
    Binance USDT-M Futures Broker Adapter.
    Replaces the legacy OrderExecutor and DataFetcher scripts.
    """
    def __init__(self):
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret
        self.symbol = settings.symbol
        self.base_url = "https://testnet.binancefuture.com" if settings.binance_testnet else "https://fapi.binance.com"
        
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json",
        })
        
        # Load formatting precisions
        self.price_decimals, self.qty_decimals = self._load_tick_and_step()
        logger.info("Binance adapter initialized", testnet=settings.binance_testnet, price_decimals=self.price_decimals)

    def _load_tick_and_step(self, default_price_dp: int = 2, default_qty_dp: int = 3) -> Tuple[int, int]:
        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/exchangeInfo", timeout=(3, 10))
            r.raise_for_status()
            data = r.json()
            sym = next((s for s in data["symbols"] if s["symbol"] == self.symbol), None)
            if sym is None:
                return default_price_dp, default_qty_dp
            
            tick_size = step_size = None
            for f in sym["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = f["tickSize"]
                elif f["filterType"] == "LOT_SIZE":
                    step_size = f["stepSize"]
            
            def decimals_of(val: str) -> int:
                if "." not in val: return 0
                return len(val.split(".", 1)[1].rstrip("0"))
                
            return (decimals_of(tick_size) if tick_size else default_price_dp, 
                    decimals_of(step_size) if step_size else default_qty_dp)
        except Exception as e:
            logger.warning("Failed to fetch exchangeInfo", error=str(e))
            return default_price_dp, default_qty_dp

    def _fmt_price(self, price: Decimal) -> str:
        return f"{price:.{self.price_decimals}f}"

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self.api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def get_position(self, position_id: str) -> Optional[Position]:
        # Implementation to map Binance position info to our Position domain model
        # For simplicity, using get_positions to find it
        positions = self.get_positions()
        for p in positions:
            if p.position_id == position_id:
                return p
        return None

    def get_positions(self) -> List[Position]:
        params = self._sign({"symbol": self.symbol})
        try:
            r = self.session.get(f"{self.base_url}/fapi/v2/positionRisk", params=params, timeout=(3, 10))
            r.raise_for_status()
            data = r.json()
            
            positions = []
            if isinstance(data, list):
                for p in data:
                    amt = Decimal(str(p.get("positionAmt", "0")))
                    if abs(amt) > Decimal('0'):
                        # Simplified mapping
                        positions.append(Position(
                            position_id=self.symbol,
                            symbol=self.symbol,
                            side=OrderSide.BUY if amt > 0 else OrderSide.SELL,
                            quantity=abs(amt),
                            entry_price=Decimal(str(p.get("entryPrice", "0"))),
                            current_price=Decimal(str(p.get("markPrice", "0"))),
                            highest_price_since_entry=Decimal(str(p.get("entryPrice", "0"))), # Needs proper tracking
                            lowest_price_since_entry=Decimal(str(p.get("entryPrice", "0"))),  # Needs proper tracking
                            opened_at=None, # Needs proper fetching from orders
                            updated_at=None,
                            broker="binance_futures",
                            account_id_hash="binance_default"
                        ))
            return positions
        except Exception as e:
            logger.error("get_positions_error", error=str(e))
            return []

    def modify_stop(self, position_id: str, new_stop: Decimal, idempotency_key: str) -> bool:
        """
        In Binance, modifying a stop usually means cancelling the old ALGO order and placing a new one.
        The idempotency_key could be stored in newClientOrderId to track it.
        """
        # Fetch existing position to know the side
        pos = self.get_position(position_id)
        if not pos:
            return False
            
        side = "SELL" if pos.side == OrderSide.BUY else "BUY"
        
        # In a full implementation, we'd cancel the existing stop algo order first.
        # Then place a new STOP_MARKET conditional order via /fapi/v1/algoOrder
        
        params = {
            "algoType": "CONDITIONAL",
            "symbol": self.symbol,
            "side": side,
            "type": "STOP_MARKET",
            "triggerPrice": self._fmt_price(new_stop),
            "quantity": str(pos.quantity),
            "reduceOnly": "true",
            "timeInForce": "GTC",
            "clientOrderId": idempotency_key[:36] # max length 36
        }
        
        signed_params = self._sign(params)
        try:
            r = self.session.post(f"{self.base_url}/fapi/v1/algoOrder", params=signed_params, timeout=(3, 10))
            if r.status_code == 200:
                logger.info("stop_modified", new_stop=str(new_stop), idempotency_key=idempotency_key)
                return True
            else:
                logger.error("stop_modify_failed", status=r.status_code, response=r.text)
                return False
        except Exception as e:
            logger.error("stop_modify_error", error=str(e))
            return False

    def close_position(self, position_id: str) -> bool:
        pos = self.get_position(position_id)
        if not pos:
            return False
            
        side = "SELL" if pos.side == OrderSide.BUY else "BUY"
        params = self._sign({
            "symbol": self.symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(pos.quantity),
            "reduceOnly": "true"
        })
        
        try:
            r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params, timeout=(3, 10))
            return r.status_code == 200
        except Exception as e:
            logger.error("close_position_error", error=str(e))
            return False

    def open_position(self, side: OrderSide, quantity: Decimal) -> Optional[dict]:
        """
        Executes a MARKET order to open a new position.
        """
        params = self._sign({
            "symbol": self.symbol,
            "side": side.value,
            "type": "MARKET",
            "quantity": str(quantity)
        })
        
        try:
            r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params, timeout=(3, 10))
            if r.status_code == 200:
                data = r.json()
                logger.info("MARKET_ORDER_FILLED", side=side.value, qty=str(quantity), order_id=data.get("orderId"))
                return data
            else:
                logger.error("MARKET_ORDER_FAILED", status=r.status_code, response=r.text)
                return None
        except Exception as e:
            logger.error("open_position_error", error=str(e))
            return None

    def health_check(self) -> bool:
        try:
            params = self._sign({})
            r = self.session.get(f"{self.base_url}/fapi/v2/account", params=params, timeout=(3, 10))
            return r.status_code == 200
        except Exception:
            return False
