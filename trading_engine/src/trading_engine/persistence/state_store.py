from abc import ABC, abstractmethod
from typing import Optional
from trading_engine.models.position import Position
from trading_engine.policies.base import TrailingState

class StateStore(ABC):
    @abstractmethod
    def get_position(self, position_id: str) -> Optional[Position]:
        pass

    @abstractmethod
    def save_position(self, position: Position) -> None:
        pass
        
    @abstractmethod
    def get_trailing_state(self, position_id: str) -> Optional[TrailingState]:
        pass
        
    @abstractmethod
    def save_trailing_state(self, state: TrailingState) -> None:
        pass
