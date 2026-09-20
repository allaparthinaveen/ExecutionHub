import json
from typing import Optional, Dict
from trading_engine.persistence.state_store import StateStore
from trading_engine.models.position import Position
from trading_engine.policies.base import TrailingState

class JSONStateStore(StateStore):
    """
    Simple JSON-backed persistence replacing the legacy position_manager.py.
    """
    def __init__(self, file_path: str = "trading_engine.json"):
        self.file_path = file_path
        self.positions: Dict[str, Position] = {}
        self.trailing_states: Dict[str, TrailingState] = {}
        # In a real implementation, it would read from file_path upon init
        
    def get_position(self, position_id: str) -> Optional[Position]:
        return self.positions.get(position_id)

    def save_position(self, position: Position) -> None:
        self.positions[position.position_id] = position
        self._flush()
        
    def get_trailing_state(self, position_id: str) -> Optional[TrailingState]:
        return self.trailing_states.get(position_id)
        
    def save_trailing_state(self, state: TrailingState) -> None:
        self.trailing_states[state.position_id] = state
        self._flush()
        
    def _flush(self):
        # Implementation to write self.positions and self.trailing_states to self.file_path
        # using json.dumps with custom decimal encoding.
        pass
