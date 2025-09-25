from typing import List

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from sqlalchemy import DateTime, func

from app.db.base import Base, TimestampMixin

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    ibkr_paper_username: Mapped[str] = mapped_column(String(255))
    ibkr_paper_password: Mapped[str] = mapped_column(String(255))
    ibkr_paper_account_id: Mapped[str] = mapped_column(String(255))
    
    ibkr_live_username: Mapped[str] = mapped_column(String(255))
    ibkr_live_password: Mapped[str] = mapped_column(String(255))
    ibkr_live_account_id: Mapped[str] = mapped_column(String(255))

    bots: Mapped[List["Bot"]] = relationship(back_populates="owner")

