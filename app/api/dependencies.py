from typing import Generator
from app.models.base import SessionLocal

def get_db() -> Generator:
    """Dependency for injecting SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
