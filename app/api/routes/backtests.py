import uuid
from typing import List

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.celery_app import celery_app
from app.models import Backtest, Bot
from app.models.bot import BotStatusEnum
from app.schemas import BacktestRun, BacktestRead


router = APIRouter()


@router.post("/run")
async def run_backtest(backtest_in: BacktestRun, current_user: CurrentUser, db: DBSession):
    print(backtest_in)
    # ensure bot belongs to current user
    res = await db.execute(select(Bot).where(Bot.id == backtest_in.bot_id))
    bot = res.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    # optional: enforce ownership if Bot has owner relation loaded elsewhere
    # if bot.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Forbidden")

    # update bot status to BACKTESTING
    try:
        bot.bot_status = BotStatusEnum.BACKTESTING  # type: ignore[assignment]
    except Exception:
        bot.bot_status = "BACKTESTING"  # fallback if enum mapping differs
    await db.commit()

    # enqueue task; let Celery assign unique task_id so multiple tasks are processed
    task_payload = backtest_in.model_dump()
    celery_app.send_task("backtests.run", args=[task_payload])
    return {"message": "Backtest queued", "bot_id": bot.id}


@router.get("/{bot_id}", response_model=BacktestRead)
async def backtest_results(bot_id: str, db: DBSession) -> BacktestRead:
    res = await db.execute(
        select(Backtest)
        .where(Backtest.bot_id == bot_id)
        .order_by(Backtest.created_at.desc())
        .limit(1)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Backtest not found")

    return BacktestRead.model_validate(item)
