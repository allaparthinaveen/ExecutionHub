from fastapi import APIRouter, Depends
from typing import List
from app.schemas.shannon import DeployStrategyRequest, PortfolioStatusResponse, TradeAction
from app.services.shannon import ShannonService
from app.services.broker import BrokerService
from app.api.dependencies import get_db, get_current_user, get_auth_context, AuthContext
from app.core.config import settings
from sqlalchemy.orm import Session

router = APIRouter()

# Factory dependency to build ShannonService dynamically
def get_shannon_service_factory(db: Session = Depends(get_db)):
    def _create(user_id: str = "default_user") -> ShannonService:
        broker = BrokerService(
            api_key=settings.ANGEL_ONE_API_KEY,
            client_code=settings.ANGEL_ONE_CLIENT_CODE,
            password=settings.ANGEL_ONE_PASSWORD,
            totp_secret=settings.ANGEL_ONE_TOTP_SECRET,
            paper_trade=settings.PAPER_TRADE
        )
        return ShannonService(broker=broker, db=db, user_id=user_id)
    return _create

@router.get("/portfolio", response_model=PortfolioStatusResponse)
async def get_portfolio(
    user_id: str = Depends(get_current_user),
    service_factory = Depends(get_shannon_service_factory)
):
    service = service_factory(user_id=user_id)
    return await service.get_portfolio_status()

@router.post("/deploy")
async def deploy_strategy(
    request: DeployStrategyRequest,
    user_id: str = Depends(get_current_user),
    service_factory = Depends(get_shannon_service_factory)
):
    service = service_factory(user_id=user_id)
    return await service.deploy_strategy(request)

@router.get("/history", response_model=List[TradeAction])
async def get_history(
    user_id: str = Depends(get_current_user),
    service_factory = Depends(get_shannon_service_factory)
):
    service = service_factory(user_id=user_id)
    return await service.get_history()

@router.post("/rebalance")
async def trigger_rebalance(
    auth: AuthContext = Depends(get_auth_context),
    service_factory = Depends(get_shannon_service_factory)
):
    if auth.is_admin:
        # System-level trigger: rebalance all active configurations in the DB
        service = service_factory()
        return await service.rebalance_all_active_strategies()
    else:
        # User-level trigger: rebalance only for the current authenticated user
        service = service_factory(user_id=auth.user_id)
        return await service.trigger_rebalance()
