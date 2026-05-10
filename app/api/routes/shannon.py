from fastapi import APIRouter, Depends
from typing import List
from app.schemas.shannon import DeployStrategyRequest, PortfolioStatusResponse, TradeAction
from app.services.shannon import ShannonService
from app.services.broker import BrokerService
from datetime import datetime

router = APIRouter()

# Dependency to get ShannonService (Ideally injected from DI container or connection pool)
def get_shannon_service() -> ShannonService:
    # Dummy broker instantiation for now
    broker = BrokerService(api_key="mock", client_code="mock", password="mock", totp_secret="mock")
    return ShannonService(broker=broker)

@router.get("/portfolio", response_model=PortfolioStatusResponse)
async def get_portfolio(service: ShannonService = Depends(get_shannon_service)):
    return await service.get_portfolio_status()

@router.post("/deploy")
async def deploy_strategy(request: DeployStrategyRequest, service: ShannonService = Depends(get_shannon_service)):
    return await service.deploy_strategy(request)

@router.get("/history", response_model=List[TradeAction])
async def get_history():
    # Returning dummy data as per prompt
    return [
        TradeAction(
            date=datetime.now(),
            action="SELL",
            asset="GOLDBEES-EQ",
            qty=12,
            price=71.50,
            reason="Drift exceeded 5%"
        ),
        TradeAction(
            date=datetime.now(),
            action="BUY",
            asset="NIFTYBEES-EQ",
            qty=3,
            price=270.25,
            reason="Drift exceeded 5%"
        )
    ]

@router.post("/rebalance")
async def trigger_rebalance():
    return {"message": "Rebalance triggered", "actions": []}
