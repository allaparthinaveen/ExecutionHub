from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("tradeservices.exceptions")

class BrokerAPIException(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)}
    )

async def broker_exception_handler(request: Request, exc: BrokerAPIException):
    logger.error(f"Broker API Error on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": "Broker API Error", "message": exc.message}
    )
