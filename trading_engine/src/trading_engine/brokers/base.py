from abc import ABC, abstractmethod
from typing import List, Optional
from decimal import Decimal
from trading_engine.models.position import Position

class BrokerAdapter(ABC):
    @abstractmethod
    def get_position(self, position_id: str) -> Optional[Position]:
        pass
        
    @abstractmethod
    def get_positions(self) -> List[Position]:
        pass
        
    @abstractmethod
    def modify_stop(self, position_id: str, new_stop: Decimal, idempotency_key: str) -> bool:
        pass
        
    @abstractmethod
    def close_position(self, position_id: str) -> bool:
        pass
        
    @abstractmethod
    def health_check(self) -> bool:
        pass
