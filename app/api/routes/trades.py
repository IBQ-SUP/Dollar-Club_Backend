from typing import List

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.celery_app import celery_app
from app.models import Bot, Trade
from app.schemas.trade import TradeRead, TradeRun
from app.models.bot import BotStatusEnum


router = APIRouter()


@router.get("/", response_model=List[TradeRead])
async def list_trades(current_user: CurrentUser, db: DBSession) -> List[TradeRead]:
    res = await db.execute(select(Trade).join(Bot).where(Bot.owner_id == current_user.id))
    trades = res.scalars().all()
    return [TradeRead.model_validate(t) for t in trades]

@router.post("/run")
async def run_trade(trade_in: TradeRun, current_user: CurrentUser, db: DBSession):
    print(trade_in)
    res = await db.execute(select(Bot).where(Bot.id == trade_in.bot_id))
    bot = res.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # update bot status to LIVE
    try:
        bot.bot_status = BotStatusEnum.LIVE  # type: ignore[assignment]
    except Exception:
        bot.bot_status = "LIVE"  # fallback if enum mapping differs
    await db.commit()

    # enqueue task with a unique id
    task_payload = trade_in.model_dump()
    celery_app.send_task("trades.run", args=[task_payload, current_user.id], task_id=f"trade_{bot.id}")
    return {"message": "trading queued", "bot_id": bot.id}
    