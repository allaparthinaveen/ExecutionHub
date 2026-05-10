from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.models.base import Base

class ShannonConfig(Base):
    __tablename__ = "shannon_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    asset_a = Column(String, nullable=False)
    asset_b = Column(String, nullable=False)
    target_a = Column(Float, default=0.5)
    target_b = Column(Float, default=0.5)
    threshold = Column(Float, default=0.05)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ShannonTradeHistory(Base):
    __tablename__ = "shannon_trade_history"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("shannon_configs.id"), nullable=False)
    action = Column(String, nullable=False) # BUY or SELL
    asset = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    reason = Column(String)
    executed_at = Column(DateTime(timezone=True), server_default=func.now())
