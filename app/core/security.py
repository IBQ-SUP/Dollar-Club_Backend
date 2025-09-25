from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _create_token(subject: str, expires_minutes: int, token_type: str) -> str:
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode = {"sub": subject, "exp": expire_at, "type": token_type}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    return _create_token(subject, expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES, "access")


def create_refresh_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    return _create_token(subject, expires_minutes or settings.REFRESH_TOKEN_EXPIRE_MINUTES, "refresh")


async def get_user_from_token(token: str, db: AsyncSession) -> Optional[User]:
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    subject = payload.get("sub")
    if subject is None:
        return None
    stmt = select(User).where((User.email == subject) | (User.id == subject))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    return user
    
