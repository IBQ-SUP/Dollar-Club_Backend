import uuid
from typing import List

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DBSession
from app.models.bot import Bot, BotStatusEnum
from app.models.backtest import Backtest
from app.schemas.bot import BotCreate, BotUpdate, BotMyRead, BotAllRead
from app.models.user import User


router = APIRouter()


@router.post("/create")
async def create_bot(bot_in: BotCreate, current_user: CurrentUser, db: DBSession):
    bot = Bot(
        id=str(uuid.uuid4()),
        name=bot_in.name,
        description=bot_in.description,
        parameters=bot_in.parameters,
        strategy=bot_in.strategy,
        owner_id=current_user.id,
    )

    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    return {"message": "Bot created", "id": bot.id}


@router.get("/all_bots", response_model=List[BotAllRead])
async def all_bots(db: DBSession) -> List[BotAllRead]:
    res = await db.execute(
        select(Bot, User.username).join(User, Bot.owner_id == User.id).where(or_(Bot.bot_status == BotStatusEnum.LIVE, 
        Bot.bot_status == BotStatusEnum.PAUSED))
    )
    rows = res.all()

    return [
        BotAllRead.model_validate(
            {
                "id": bot.id,
                "name": bot.name,
                "description": bot.description,
                "strategy": bot.strategy,
                "bot_status": bot.bot_status,
                "owner_name": username,
                "updated_at": bot.updated_at,
                "parameters": bot.parameters,
            }
        )
        for bot, username in rows
    ]


@router.get("/my_bots", response_model=List[BotMyRead])
async def get_bot(current_user: CurrentUser, db: DBSession) -> List[BotMyRead]:
    res = await db.execute(select(Bot).where(Bot.owner_id == current_user.id))
    bots = res.scalars().all()

    return [BotMyRead.model_validate(b) for b in bots]


@router.patch("/{bot_id}", response_model=BotMyRead)
async def update_bot(bot_id: str, bot_in: BotUpdate, current_user: CurrentUser, db: DBSession) -> BotMyRead:
    res = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id))
    bot = res.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot_in.description is not None:
        bot.description = bot_in.description
    if bot_in.parameters is not None:
        bot.parameters = bot_in.parameters

    bot.bot_status = BotStatusEnum.PENDING

    await db.commit()
    await db.refresh(bot)
    return BotMyRead.model_validate(bot)


@router.delete("/{bot_id}")
async def delete_bot(bot_id: str, current_user: CurrentUser, db: DBSession) -> dict:
    # Ensure the bot exists and belongs to the current user before deleting anything
    res = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id))
    bot = res.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Bulk-delete related backtests in a single statement (faster, fewer commits)
    await db.execute(delete(Backtest).where(Backtest.bot_id == bot_id))

    # Delete the bot itself and commit once
    await db.delete(bot)
    await db.commit()
    return {"status": "deleted"}

@router.patch("/{bot_id}/toggle_status", response_model=BotMyRead)
async def pause_bot(bot_id: str, current_user: CurrentUser, db: DBSession) -> BotMyRead:
    res = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id))
    bot = res.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    if bot.bot_status == BotStatusEnum.LIVE:
        bot.bot_status = BotStatusEnum.PAUSED
    elif bot.bot_status == BotStatusEnum.PAUSED:
        bot.bot_status = BotStatusEnum.LIVE
    
    await db.commit()
    await db.refresh(bot)
    return BotMyRead.model_validate(bot)