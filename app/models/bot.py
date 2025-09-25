from typing import Dict, List, Optional

from sqlalchemy import ForeignKey, JSON, String, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, func, Numeric
from datetime import datetime
from enum import Enum as PyEnum

from app.db.base import Base, TimestampMixin
# Avoid direct model imports here to prevent circular imports; use string refs in relationships

class BotStatusEnum(str, PyEnum):
    PENDING = "PENDING"
    BACKTESTING = "BACKTESTING"
    BACKTESTED = "BACKTESTED"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class Bot(TimestampMixin, Base):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy: Mapped[str] = mapped_column(String(120))
    parameters: Mapped[Dict] = mapped_column(JSON, default=dict)

    bot_status: Mapped[BotStatusEnum] = mapped_column(SAEnum(BotStatusEnum, name="bot_status_enum"), default=BotStatusEnum.PENDING)
    
    # created_at/updated_at already provided by TimestampMixin
    stop_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    paper_trade_return: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0)
    live_trade_return: Mapped[float] = mapped_column(Numeric(20, 8), default=0.0)

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    owner: Mapped["User"] = relationship(back_populates="bots")

    backtests: Mapped[List["Backtest"]] = relationship(back_populates="bot")
    trades: Mapped[List["Trade"]] = relationship(back_populates="bot")

