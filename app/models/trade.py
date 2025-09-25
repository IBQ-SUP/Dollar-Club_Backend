from datetime import datetime
import uuid

from sqlalchemy import ForeignKey, Numeric, String, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship


from app.db.base import Base, TimestampMixin


class Trade(TimestampMixin, Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bot_id: Mapped[str] = mapped_column(String(36), ForeignKey("bots.id"), index=True)
    bot: Mapped["Bot"] = relationship(back_populates="trades")

    event_timestamp: Mapped[datetime] = mapped_column()
    order_id: Mapped[str] = mapped_column(String(36))
    symbol: Mapped[str] = mapped_column(String(32))
    asset_type: Mapped[str] = mapped_column(String(36))
    option_right: Mapped[str] = mapped_column(String(16))
    expiration: Mapped[datetime] = mapped_column(DateTime)
    strike: Mapped[float] = mapped_column(Numeric(20, 8))
    multiplier: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Numeric(20, 8))
    price: Mapped[float] = mapped_column(Numeric(20, 8))
    trade_value: Mapped[float] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(16))