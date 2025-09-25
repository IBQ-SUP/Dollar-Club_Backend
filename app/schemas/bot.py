from typing import Any, Dict, Optional

from pydantic import BaseModel
from datetime import datetime


class BotBase(BaseModel):
    name: str
    description: Optional[str] = None
    strategy: str
    parameters: Dict[str, Any] = {}


class BotCreate(BotBase):
    pass


class BotUpdate(BaseModel):
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class BotMyRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    strategy: str
    bot_status: str
    parameters: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    owner_id: str

    class Config:
        from_attributes = True


class BotAllRead(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    strategy: str
    bot_status: str
    owner_name: str
    updated_at: datetime
    parameters: Dict[str, Any]


    class Config:
        from_attributes = True
