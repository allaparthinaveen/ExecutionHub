from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from decimal import Decimal

from trading_engine.models.position import Position
from trading_engine.models.market import MarketState
from trading_engine.core.decision import TrailingDecision

class TrailingState:
    def __init__(self, position_id: str):
        self.position_id = position_id
        self.activation_state: bool = False
        self.activation_timestamp: Optional[str] = None
        self.initial_risk: Optional[Decimal] = None
        self.highest_price: Optional[Decimal] = None
        self.lowest_price: Optional[Decimal] = None
        self.current_stop: Optional[Decimal] = None
        self.last_stop_update: Optional[Decimal] = None
        self.last_stop_update_timestamp: Optional[str] = None
        self.policy_version: Optional[str] = None
        self.metadata: Dict[str, Any] = {}

class TrailingPolicy(ABC):
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the policy."""
        pass
        
    @property
    @abstractmethod
    def version(self) -> str:
        """Version of the policy."""
        pass
        
    @property
    @abstractmethod
    def configuration_hash(self) -> str:
        """Hash of the policy configuration to ensure reproducibility."""
        pass

    @abstractmethod
    def evaluate(
        self,
        position: Position,
        market: MarketState,
        state: TrailingState,
    ) -> TrailingDecision:
        """
        Evaluate the current market and position state to produce a trailing decision.
        Policies calculate decisions only. They never modify broker orders.
        """
        pass
