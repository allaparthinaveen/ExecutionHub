import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.schemas.shannon import DeployStrategyRequest, PortfolioStatusResponse, AssetStatus, TradeAction
from app.models.trading import ShannonConfig, ShannonTradeHistory
from app.services.broker import BrokerService

logger = logging.getLogger("tradeservices.shannon")

class ShannonService:
    def __init__(self, broker: BrokerService, db: Session, user_id: str = "default_user"):
        self.broker = broker
        self.db = db
        self.user_id = user_id

    async def get_portfolio_status(self) -> PortfolioStatusResponse:
        logger.info("Fetching portfolio status")
        
        # 1. Get active config
        config = self.db.query(ShannonConfig).filter(
            ShannonConfig.user_id == self.user_id,
            ShannonConfig.is_active == True
        ).first()

        if not config:
            return PortfolioStatusResponse(
                total_value=0.0,
                pnl_today=0.0,
                rebalance_needed=False,
                threshold=5.0,
                assets=[]
            )

        # 2. Fetch live prices
        price_a = await self.broker.fetch_price(config.asset_a)
        price_b = await self.broker.fetch_price(config.asset_b)

        # 3. Calculate current holdings from trade history
        # (Alternatively query broker directly, but doing DB aggregation for self-contained logic)
        trades = self.db.query(ShannonTradeHistory).filter(
            ShannonTradeHistory.config_id == config.id
        ).all()

        qty_a = 0
        qty_b = 0
        for t in trades:
            modifier = 1 if t.action == 'BUY' else -1
            if t.asset == config.asset_a:
                qty_a += (t.quantity * modifier)
            elif t.asset == config.asset_b:
                qty_b += (t.quantity * modifier)

        value_a = qty_a * price_a
        value_b = qty_b * price_b
        total_value = value_a + value_b

        if total_value == 0:
            return PortfolioStatusResponse(
                total_value=0.0,
                pnl_today=0.0,
                rebalance_needed=False,
                threshold=config.threshold * 100,
                assets=[
                    AssetStatus(ticker=config.asset_a, target_weight=config.target_a * 100, current_weight=0.0, drift=0.0, value=0.0, price=price_a),
                    AssetStatus(ticker=config.asset_b, target_weight=config.target_b * 100, current_weight=0.0, drift=0.0, value=0.0, price=price_b)
                ]
            )

        current_weight_a = (value_a / total_value)
        current_weight_b = (value_b / total_value)

        drift_a = abs(current_weight_a - config.target_a)
        drift_b = abs(current_weight_b - config.target_b)
        
        # We define drift as the maximum deviation across assets
        max_drift = max(drift_a, drift_b)
        rebalance_needed = max_drift > config.threshold

        return PortfolioStatusResponse(
            total_value=total_value,
            pnl_today=0.0, # Implement PnL calculation later (requires tracking initial investment vs current)
            rebalance_needed=rebalance_needed,
            threshold=config.threshold * 100,
            assets=[
                AssetStatus(
                    ticker=config.asset_a,
                    target_weight=config.target_a * 100,
                    current_weight=current_weight_a * 100,
                    drift=drift_a * 100,
                    value=value_a,
                    price=price_a
                ),
                AssetStatus(
                    ticker=config.asset_b,
                    target_weight=config.target_b * 100,
                    current_weight=current_weight_b * 100,
                    drift=drift_b * 100,
                    value=value_b,
                    price=price_b
                )
            ]
        )

    async def deploy_strategy(self, request: DeployStrategyRequest) -> dict:
        logger.info(f"Deploying strategy with {request.amount} for {request.asset_a} and {request.asset_b}")
        
        # Deactivate any existing configs for this user to ensure only 1 runs at a time
        existing_configs = self.db.query(ShannonConfig).filter(
            ShannonConfig.user_id == self.user_id,
            ShannonConfig.is_active == True
        ).all()
        for c in existing_configs:
            c.is_active = False
        self.db.commit()

        # Create new config (storing percentages as decimals)
        config = ShannonConfig(
            user_id=self.user_id,
            asset_a=request.asset_a,
            asset_b=request.asset_b,
            target_a=0.5,
            target_b=0.5,
            threshold=(request.threshold / 100.0)
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)

        # Execute Initial Trades (50/50 split)
        price_a = await self.broker.fetch_price(request.asset_a)
        price_b = await self.broker.fetch_price(request.asset_b)
        
        qty_a = int((request.amount * 0.5) / price_a)
        qty_b = int((request.amount * 0.5) / price_b)
        
        if qty_a > 0:
            order_a = await self.broker.place_order(request.asset_a, "BUY", qty_a)
            trade_a = ShannonTradeHistory(
                config_id=config.id, action="BUY", asset=request.asset_a,
                quantity=qty_a, price=price_a, amount=qty_a * price_a, reason="Initial Deployment"
            )
            self.db.add(trade_a)

        if qty_b > 0:
            order_b = await self.broker.place_order(request.asset_b, "BUY", qty_b)
            trade_b = ShannonTradeHistory(
                config_id=config.id, action="BUY", asset=request.asset_b,
                quantity=qty_b, price=price_b, amount=qty_b * price_b, reason="Initial Deployment"
            )
            self.db.add(trade_b)
            
        self.db.commit()
        
        return {
            "status": "success",
            "message": f"Successfully deployed ₹{request.amount} across {request.asset_a} and {request.asset_b}.",
        }
        
    async def get_history(self) -> List[TradeAction]:
        config = self.db.query(ShannonConfig).filter(
            ShannonConfig.user_id == self.user_id,
            ShannonConfig.is_active == True
        ).first()

        if not config:
            return []

        trades = self.db.query(ShannonTradeHistory).filter(
            ShannonTradeHistory.config_id == config.id
        ).order_by(ShannonTradeHistory.executed_at.desc()).all()
        
        return [
            TradeAction(
                date=t.executed_at,
                action=t.action,
                asset=t.asset,
                qty=t.quantity,
                price=t.price,
                reason=t.reason
            ) for t in trades
        ]

    async def trigger_rebalance(self) -> dict:
        """Runs the drift check and executes rebalancing orders if needed."""
        logger.info("Triggering manual rebalance check...")
        
        config = self.db.query(ShannonConfig).filter(
            ShannonConfig.user_id == self.user_id,
            ShannonConfig.is_active == True
        ).first()

        if not config:
            return {"status": "error", "message": "No active strategy found to rebalance."}

        status = await self.get_portfolio_status()
        
        if not status.rebalance_needed:
            return {"status": "skipped", "message": "Portfolio is within drift limits. No rebalance needed."}
            
        target_value_a = status.total_value * config.target_a
        target_value_b = status.total_value * config.target_b
        
        asset_a_status = status.assets[0]
        asset_b_status = status.assets[1]
        
        actions_taken = []
        
        # Determine buys/sells for Asset A
        diff_a = target_value_a - asset_a_status.value
        qty_to_trade_a = int(abs(diff_a) / asset_a_status.price)
        
        if qty_to_trade_a > 0:
            action_a = "BUY" if diff_a > 0 else "SELL"
            await self.broker.place_order(asset_a_status.ticker, action_a, qty_to_trade_a)
            trade_a = ShannonTradeHistory(
                config_id=config.id, action=action_a, asset=asset_a_status.ticker,
                quantity=qty_to_trade_a, price=asset_a_status.price, amount=qty_to_trade_a * asset_a_status.price, reason=f"Drift exceeded {config.threshold * 100}%"
            )
            self.db.add(trade_a)
            actions_taken.append(f"{action_a} {qty_to_trade_a} of {asset_a_status.ticker}")

        # Determine buys/sells for Asset B
        diff_b = target_value_b - asset_b_status.value
        qty_to_trade_b = int(abs(diff_b) / asset_b_status.price)
        
        if qty_to_trade_b > 0:
            action_b = "BUY" if diff_b > 0 else "SELL"
            await self.broker.place_order(asset_b_status.ticker, action_b, qty_to_trade_b)
            trade_b = ShannonTradeHistory(
                config_id=config.id, action=action_b, asset=asset_b_status.ticker,
                quantity=qty_to_trade_b, price=asset_b_status.price, amount=qty_to_trade_b * asset_b_status.price, reason=f"Drift exceeded {config.threshold * 100}%"
            )
            self.db.add(trade_b)
            actions_taken.append(f"{action_b} {qty_to_trade_b} of {asset_b_status.ticker}")

        self.db.commit()

        return {
            "status": "success",
            "message": "Rebalance executed successfully.",
            "actions": actions_taken
        }

    async def rebalance_all_active_strategies(self) -> dict:
        """Runs the drift check and executes rebalancing for all active strategies."""
        logger.info("Triggering automated rebalance check for all active strategies...")
        active_configs = self.db.query(ShannonConfig).filter(
            ShannonConfig.is_active == True
        ).all()
        
        results = []
        for config in active_configs:
            user_service = ShannonService(broker=self.broker, db=self.db, user_id=config.user_id)
            res = await user_service.trigger_rebalance()
            results.append({"user_id": config.user_id, "result": res})
            
        return {"status": "success", "results": results}
