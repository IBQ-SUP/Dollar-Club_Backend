import asyncio
import os

from lumibot.traders import Trader
from lumibot.entities import Asset
from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.services.wheel import WheelOptionStrategy
from app.services.short_straddle import ShortStraddleStrategy
from app.services.short_strangle import ShortStrangleStrategy
from app.schemas.trade import TradeRun

@celery_app.task(name="trades.run")
def run_trade(trade_in: dict | TradeRun, user_id: str):
    # Validate input
    if isinstance(trade_in, dict):
        trade_run = TradeRun.model_validate(trade_in)
    else:
        trade_run = trade_in
    # ------------------------------------------------------------------
    # LIVE / PAPER TRADING – we programmatically set IBKR credentials so
    # the Trader picks them up without needing a .env file.
    # ------------------------------------------------------------------
    # Load user from DB to get credentials
    async def _load_user(uid: str):
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from app.models.user import User
            res = await db.execute(select(User).where(User.id == uid))
            return res.scalar_one_or_none()

    user = asyncio.get_event_loop().run_until_complete(_load_user(user_id))
    if not user:
        raise ValueError("User not found for trading credentials")
    
    print(trade_run.trade_type)
    print(user.ibkr_paper_username)
    print(user.ibkr_paper_password)
    if trade_run.trade_type == "paper":
        os.environ["IB_IS_PRODUCTION"] = "False"
        os.environ["IB_USERNAME"] = user.ibkr_paper_username
        os.environ["IB_PASSWORD"] = user.ibkr_paper_password
        os.environ["IB_ACCOUNT_ID"] = user.ibkr_paper_account_id
        os.environ["IB_GATEWAY_PORT"] = "7497"
    elif trade_run.trade_type == "live":
        os.environ["IB_IS_PRODUCTION"] = "True"
        os.environ["IB_USERNAME"] = user.ibkr_live_username
        os.environ["IB_PASSWORD"] = user.ibkr_live_password
        os.environ["IB_ACCOUNT_ID"] = user.ibkr_live_account_id
        os.environ["IB_GATEWAY_PORT"] = "7496"


    # Gateway connection details
    os.environ["IB_GATEWAY_HOST"] = "127.0.0.1"
    os.environ["IB_GATEWAY_IP"] = "127.0.0.1"  # some installations use _IP, others _HOST

    strategy_str = trade_run.strategy

    match strategy_str:
        case "wheel":
            strategy_class = WheelOptionStrategy
        case "short_straddle":
            strategy_class = ShortStraddleStrategy
        case "short_strangle":
            strategy_class = ShortStrangleStrategy
        case _:
            raise ValueError(f"Invalid strategy: {strategy_str}")

    parameters = dict(trade_run.params or {})
    parameters["bot_id"] = trade_run.bot_id
    
    trader = Trader()
    strategy = strategy_class(
        parameters=parameters,
        quote_asset=Asset("USD", Asset.AssetType.FOREX)
    )
    trader.add_strategy(strategy)
    trader.run_all()
