from fastapi import APIRouter, Depends
from typing import List
from app.schemas.shannon import DeployStrategyRequest, PortfolioStatusResponse, TradeAction
from app.services.shannon import ShannonService
from app.services.broker import BrokerService
from app.api.dependencies import get_db
from app.core.config import settings
from sqlalchemy.orm import Session
from datetime import datetime

router = APIRouter()

# Dependency to get ShannonService
def get_shannon_service(db: Session = Depends(get_db)) -> ShannonService:
    broker = BrokerService(
        api_key=settings.ANGEL_ONE_API_KEY,
        client_code=settings.ANGEL_ONE_CLIENT_CODE,
        password=settings.ANGEL_ONE_PASSWORD,
        totp_secret=settings.ANGEL_ONE_TOTP_SECRET,
        paper_trade=settings.PAPER_TRADE
    )
    return ShannonService(broker=broker, db=db)

@router.get("/portfolio", response_model=PortfolioStatusResponse)
async def get_portfolio(service: ShannonService = Depends(get_shannon_service)):
    return await service.get_portfolio_status()

@router.post("/deploy")
async def deploy_strategy(request: DeployStrategyRequest, service: ShannonService = Depends(get_shannon_service)):
    return await service.deploy_strategy(request)

@router.get("/history", response_model=List[TradeAction])
async def get_history(service: ShannonService = Depends(get_shannon_service)):
    return await service.get_history()

@router.post("/rebalance")
async def trigger_rebalance(service: ShannonService = Depends(get_shannon_service)):
    return await service.trigger_rebalance()
