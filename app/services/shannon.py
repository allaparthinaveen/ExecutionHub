import logging
from app.schemas.shannon import DeployStrategyRequest, PortfolioStatusResponse, AssetStatus
from app.services.broker import BrokerService

logger = logging.getLogger("tradeservices.shannon")

class ShannonService:
    def __init__(self, broker: BrokerService):
        self.broker = broker

    async def get_portfolio_status(self) -> PortfolioStatusResponse:
        """Mock returning portfolio status for the dummy mobile UI integration."""
        logger.info("Fetching portfolio status")
        price_a = await self.broker.fetch_price("NIFTYBEES-EQ")
        price_b = await self.broker.fetch_price("GOLDBEES-EQ")
        
        # Hardcoding logic to match the v0 prompt requirements
        return PortfolioStatusResponse(
            total_value=254320.50,
            pnl_today=1240.20,
            rebalance_needed=False,
            threshold=5.0,
            assets=[
                AssetStatus(
                    ticker="NIFTYBEES-EQ",
                    target_weight=50.0,
                    current_weight=48.5,
                    drift=1.5,
                    value=123345.44,
                    price=price_a
                ),
                AssetStatus(
                    ticker="GOLDBEES-EQ",
                    target_weight=50.0,
                    current_weight=51.5,
                    drift=1.5,
                    value=130975.06,
                    price=price_b
                )
            ]
        )

    async def deploy_strategy(self, request: DeployStrategyRequest) -> dict:
        """Deploy Shannon's demon. Calculates initial 50/50 split and executes orders."""
        logger.info(f"Deploying strategy with {request.amount} for {request.asset_a} and {request.asset_b}")
        
        price_a = await self.broker.fetch_price(request.asset_a)
        price_b = await self.broker.fetch_price(request.asset_b)
        
        qty_a = int((request.amount * 0.5) / price_a)
        qty_b = int((request.amount * 0.5) / price_b)
        
        # In a real app, save to DB here
        
        order_a = await self.broker.place_order(request.asset_a, "BUY", qty_a)
        order_b = await self.broker.place_order(request.asset_b, "BUY", qty_b)
        
        return {
            "status": "success",
            "message": f"Successfully deployed ₹{request.amount} across {request.asset_a} and {request.asset_b}.",
            "orders": [order_a, order_b]
        }
