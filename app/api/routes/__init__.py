from fastapi import APIRouter

from . import health, auth, users, bots, backtests, trades


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(backtests.router, prefix="/backtests", tags=["backtests"])
api_router.include_router(trades.router, prefix="/trades", tags=["trades"])


