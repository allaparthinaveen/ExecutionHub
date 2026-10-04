from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from pydantic import BaseModel
from app.models.base import SessionLocal
from app.core.config import settings

class AuthContext(BaseModel):
    user_id: Optional[str] = None
    is_admin: bool = False

security = HTTPBearer(auto_error=False)

def get_db() -> Generator:
    """Dependency for injecting SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY")
) -> AuthContext:
    # 1. Try API Key first
    if x_api_key:
        if settings.API_KEY and x_api_key == settings.API_KEY:
            return AuthContext(is_admin=True)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key"
        )
    
    # 2. Try JWT Bearer token next
    if credentials:
        token = credentials.credentials
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            user_id: str = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token payload missing 'sub' claim"
                )
            return AuthContext(user_id=user_id)
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
            
    # 3. No auth provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Provide JWT Bearer token or X-API-KEY header."
    )

async def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> str:
    if not auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User authentication required (JWT token)."
        )
    return auth.user_id
