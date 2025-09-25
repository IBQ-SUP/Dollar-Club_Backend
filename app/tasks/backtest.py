import uuid
import asyncio
from datetime import datetime

from lumibot.entities import Asset, TradingFee
from lumibot.backtesting import PolygonDataBacktesting

from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.models import Backtest, Bot, BotStatusEnum
from app.core.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from sqlalchemy.exc import DataError
from app.services.wheel import WheelOptionStrategy
from app.services.short_straddle import ShortStraddleStrategy
from app.services.short_strangle import ShortStrangleStrategy
from app.schemas.backtest import BacktestRun
from fastapi.encoders import jsonable_encoder
try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore
try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


@celery_app.task(name="backtests.run")
def run_backtest(backtest_in: dict | BacktestRun) -> dict:
    # Ensure we have a BacktestRun instance from a JSON-serializable payload
    if isinstance(backtest_in, dict):
        backtest_run = BacktestRun.model_validate(backtest_in)
    else:
        backtest_run = backtest_in
    return asyncio.run(_run_backtest(backtest_run))


async def _run_backtest(backtest_in: BacktestRun) -> dict:
    trading_fee = TradingFee(percent_fee=0.001)

    backtesting_start = backtest_in.backtesting_start
    backtesting_end = backtest_in.backtesting_end
    parameters = backtest_in.params
    strategy = backtest_in.strategy

    match strategy:
        case "wheel":
            strategy_class = WheelOptionStrategy
        case "short_straddle":
            strategy_class = ShortStraddleStrategy
        case "short_strangle":
            strategy_class = ShortStrangleStrategy
        case _:
            raise ValueError(f"Invalid strategy: {strategy}")

    results = strategy_class.backtest(
        datasource_class=PolygonDataBacktesting,
        backtesting_start=backtesting_start,
        backtesting_end=backtesting_end,
        benchmark_asset=Asset("SPY", Asset.AssetType.STOCK),
        buy_trading_fees=[trading_fee],
        sell_trading_fees=[trading_fee],
        quote_asset=Asset("USD", Asset.AssetType.FOREX),
        parameters=parameters,
        budget=100000,
    )
    # Ensure results are JSON-serializable for the JSON column
    def _to_native(value):  # recursively convert numpy/pandas types
        if isinstance(value, dict):
            return {k: _to_native(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_native(v) for v in value]
        if np is not None and isinstance(value, getattr(np, 'generic', ())):
            try:
                return value.item()
            except Exception:
                return float(value)
        if pd is not None and isinstance(value, getattr(pd, 'Timestamp', ())):
            return value.to_pydatetime().isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    safe_results = _to_native(jsonable_encoder(results))

    # Use a sync SQLAlchemy session for DB write to avoid async driver issues in Celery worker
    def _save_sync() -> str:
        sync_engine = create_engine(settings.sync_database_url, future=True, pool_pre_ping=True)
        SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)
        with SyncSessionLocal() as db:
            backtest = Backtest(
                id=str(uuid.uuid4()),
                bot_id=backtest_in.bot_id,
                start_date=backtesting_start,
                end_date=backtesting_end,
                results=safe_results,
            )
            db.add(backtest)
            db.commit()
            # Ensure enum has BACKTESTED value (idempotent). Use autocommit DO block to support older PG.
            try:
                with sync_engine.connect() as conn:
                    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    conn.execute(text(
                        """
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_type t
                                JOIN pg_enum e ON t.oid = e.enumtypid
                                WHERE t.typname = 'bot_status_enum' AND e.enumlabel = 'BACKTESTED'
                            ) THEN
                                ALTER TYPE bot_status_enum ADD VALUE 'BACKTESTED';
                            END IF;
                        END
                        $$;
                        """
                    ))
            except Exception:
                # If this fails (permissions/version), we'll skip status update below
                pass

            result = db.execute(select(Bot).where(Bot.id == backtest_in.bot_id))
            bot = result.scalar_one_or_none()
            if bot is not None:
                print(bot.id)
                print(bot.bot_status)
                try:
                    bot.bot_status = BotStatusEnum.BACKTESTED  # type: ignore[assignment]
                except Exception:
                    bot.bot_status = "BACKTESTED"
                try:
                    db.commit()
                except DataError:
                    # Fallback: don't update status if enum label not present and cannot be added
                    db.rollback()
            return backtest.id

    backtest_id = await asyncio.to_thread(_save_sync)
    # Return a JSON-serializable summary
    return {
        "backtest_id": backtest_id,
        "bot_id": backtest_in.bot_id,
        "start_date": backtesting_start.isoformat() if isinstance(backtesting_start, datetime) else str(backtesting_start),
        "end_date": backtesting_end.isoformat() if isinstance(backtesting_end, datetime) else str(backtesting_end),
        "result_summary": results,
    }
