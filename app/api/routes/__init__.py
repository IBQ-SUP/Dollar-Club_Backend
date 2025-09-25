from fastapi import APIRouter

from . import health, auth, users, bots, backtests, trades


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/api/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/api/users", tags=["users"])
api_router.include_router(bots.router, prefix="/api/bots", tags=["bots"])
api_router.include_router(backtests.router, prefix="/api/backtests", tags=["backtests"])
api_router.include_router(trades.router, prefix="/api/trades", tags=["trades"])

