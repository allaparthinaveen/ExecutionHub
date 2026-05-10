import logging
from typing import Optional
import pyotp
import yfinance as yf
from SmartApi import SmartConnect

logger = logging.getLogger("tradeservices.broker")

# Hardcoded symbol to token map for the MVP to avoid fetching massive JSON files.
# In production, you might want to fetch and cache this on startup.
TOKEN_MAP = {
    "NIFTYBEES-EQ": "10576",
    "GOLDBEES-EQ": "14428",
    "BANKBEES-EQ": "10578",
    "LIQUIDBEES-EQ": "10939"
}

class BrokerService:
    """
    Abstracted service to handle external broker communications (e.g. Angel One).
    """
    def __init__(self, api_key: str, client_code: str, password: str, totp_secret: str, paper_trade: bool = True):
        self.api_key = api_key
        self.client_code = client_code
        self.password = password
        self.totp_secret = totp_secret
        self.paper_trade = paper_trade
        self.smart_api = None
        self._connected = False

    async def connect(self) -> bool:
        """Initialize connection to Angel One."""
        if not self.api_key or not self.client_code:
            logger.warning("Broker credentials missing. Operating in fallback mode (yfinance/mock).")
            return False

        try:
            logger.info(f"Connecting to Angel One for client {self.client_code}")
            self.smart_api = SmartConnect(api_key=self.api_key)
            
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_secret).now()
            
            auth = self.smart_api.generateSession(self.client_code, self.password, totp)
            
            if auth and auth.get('status'):
                self._connected = True
                logger.info("Successfully connected to Angel One API.")
                return True
            else:
                logger.error(f"Angel Auth Failed: {auth.get('message')}")
                self._connected = False
                return False
        except Exception as e:
            logger.error(f"Failed to connect to Broker: {e}")
            self._connected = False
            return False

    async def fetch_price(self, symbol: str) -> float:
        """Fetch real-time price from Angel One, or fallback to yfinance."""
        if not self._connected:
             await self.connect()
             
        # 1. Attempt Angel One
        if self._connected and symbol in TOKEN_MAP:
            token = TOKEN_MAP[symbol]
            try:
                logger.debug(f"Fetching LTP for {symbol} ({token}) from Angel One")
                res = self.smart_api.ltpData("NSE", symbol, str(token))
                if res and res.get('status') and res.get('data', {}).get('ltp'):
                    return float(res['data']['ltp'])
            except Exception as e:
                logger.warning(f"LTP fetch failed for {symbol}: {e}. Falling back to yfinance.")

        # 2. Fallback to yfinance
        try:
            yf_symbol = symbol.replace('-EQ', '') + '.NS'
            logger.debug(f"Fetching price for {yf_symbol} from yfinance")
            ticker = yf.Ticker(yf_symbol)
            data = ticker.history(period="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except Exception as e:
            logger.error(f"yfinance fallback failed for {symbol}: {e}")

        # 3. Ultimate mock fallback so UI doesn't crash during demo
        logger.warning(f"Returning hardcoded mock price for {symbol} as last resort.")
        if "NIFTYBEES" in symbol:
            return 275.50
        elif "GOLDBEES" in symbol:
            return 72.10
        return 100.0

    async def place_order(self, symbol: str, side: str, qty: int, order_type: str = "MARKET") -> str:
        """Place an order with the broker, or simulate if PAPER_TRADE is True."""
        logger.info(f"Preparing {side} order for {qty} shares of {symbol} at {order_type}")
        
        # Guard against actual execution
        if self.paper_trade:
            logger.info(f"[PAPER TRADE] Simulated {side} {qty} {symbol}. Real order was NOT placed.")
            return f"SIM_ORD_{symbol}_{side}_{qty}"

        if not self._connected:
             success = await self.connect()
             if not success:
                 raise Exception("Broker disconnected. Cannot place real order.")

        token = TOKEN_MAP.get(symbol)
        if not token:
            raise Exception(f"Unknown symbol token for {symbol}. Cannot place real order.")

        try:
            orderparams = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": str(token),
                "transactiontype": side,
                "exchange": "NSE",
                "ordertype": order_type,
                "producttype": "DELIVERY", # Rebalancing uses Equity Delivery
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(qty)
            }
            order_response = self.smart_api.placeOrder(orderparams)
            
            if isinstance(order_response, str):
                return order_response
            
            return order_response.get('data', {}).get('orderid', str(order_response))
            
        except Exception as e:
            logger.error(f"Real order execution failed: {e}")
            raise Exception(f"Order failed: {e}")
