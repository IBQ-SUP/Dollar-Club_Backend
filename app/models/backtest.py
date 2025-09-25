from typing import Dict, Optional

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, func
from datetime import datetime

from app.db.base import Base

class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(36), ForeignKey("bots.id"), index=True)
    bot: Mapped["Bot"] = relationship(back_populates="backtests")

    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    results: Mapped[Dict] = mapped_column(JSON, default=dict)

