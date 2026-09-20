from enum import Enum, auto

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"

class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class TrailingAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    ACTIVATED = "ACTIVATED"
    MOVE_STOP = "MOVE_STOP"
    MOVE_TO_BREAKEVEN = "MOVE_TO_BREAKEVEN"
    CLOSE_POSITION = "CLOSE_POSITION"
    REJECT = "REJECT"
    ERROR = "ERROR"
