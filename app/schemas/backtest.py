from typing import Any, Dict, Optional
from datetime import datetime

from pydantic import BaseModel


class BacktestBase(BaseModel):
    params: Dict[str, Any] = {}


class BacktestRun(BacktestBase):
    strategy: str
    backtesting_start: datetime
    backtesting_end: datetime
    bot_id: str


class BacktestUpdate(BaseModel):
    status: Optional[str] = None
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BacktestRead(BacktestBase):
    id: str
    bot_id: str
    start_date: datetime
    end_date: datetime
    results: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True