from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Trade Services API"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost/dbname" # Dummy default
    
    # Authentication (If verifying tokens directly)
    SECRET_KEY: str = "super_secret_key"
    JWT_ALGORITHM: str = "HS256"
    API_KEY: Optional[str] = "super_secret_api_key"
    
    # Angel One (Broker API Defaults)
    ANGEL_ONE_API_KEY: Optional[str] = None
    ANGEL_ONE_CLIENT_CODE: Optional[str] = None
    ANGEL_ONE_PASSWORD: Optional[str] = None
    ANGEL_ONE_TOTP_SECRET: Optional[str] = None
    PAPER_TRADE: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
