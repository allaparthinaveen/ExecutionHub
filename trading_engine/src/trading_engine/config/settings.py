from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from decimal import Decimal
from typing import Optional

class TradingSettings(BaseSettings):
    # Binance API
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")
    binance_testnet: bool = Field(default=False)
    
    # Telegram
    tg_bot_token: str = Field(default="")
    tg_chat_id: str = Field(default="")
    
    # Engine configuration
    symbol: str = Field(default="XAUUSDT")
    max_positions: int = Field(default=1)
    max_lots: Decimal = Field(default=Decimal('25.0'))
    
    # Database
    db_url: str = Field(default="sqlite:///trading_engine.db")
    
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

settings = TradingSettings()
