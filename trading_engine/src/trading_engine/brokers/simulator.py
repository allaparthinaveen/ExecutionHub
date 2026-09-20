from typing import List, Optional, Dict
from decimal import Decimal
from trading_engine.brokers.base import BrokerAdapter
from trading_engine.models.position import Position

class SimulatorBroker(BrokerAdapter):
    """
    In-memory broker for safe initial testing and dry runs.
    """
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.healthy = True
        
    def get_position(self, position_id: str) -> Optional[Position]:
        return self.positions.get(position_id)
        
    def get_positions(self) -> List[Position]:
        return list(self.positions.values())
        
    def modify_stop(self, position_id: str, new_stop: Decimal, idempotency_key: str) -> bool:
        if not self.healthy:
            return False
            
        pos = self.positions.get(position_id)
        if not pos:
            return False
            
        pos.current_stop_loss = new_stop
        return True
        
    def close_position(self, position_id: str) -> bool:
        if not self.healthy:
            return False
            
        if position_id in self.positions:
            pos = self.positions[position_id]
            pos.status = "CLOSED"
            return True
        return False
        
    def health_check(self) -> bool:
        return self.healthy
        
    def _add_mock_position(self, position: Position):
        self.positions[position.position_id] = position
