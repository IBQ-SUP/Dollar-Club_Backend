from datetime import datetime

from pydantic import BaseModel, Field
from typing import Dict, Any, Literal

class TradeRead(BaseModel):
    id: str
    bot_id: str
    event_timestamp: datetime
    order_id: str
    symbol: str
    asset_type: str
    side: str
    quantity: float
    price: float
    status: str
    
    class Config:
        from_attributes = True

class TradeRun(BaseModel):
    bot_id: str
    strategy: Literal["wheel", "short_straddle", "short_strangle"]
    trade_type: Literal["paper", "live"]
    params: Dict[str, Any] = Field(default_factory=dict)