from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DBSession
from app.schemas import UserRead
from app.schemas.user import UserUpdateIbkrPaper, UserUpdateIbkrLive
from app.models.user import User

from sqlalchemy import select


router = APIRouter()

@router.get("/ibkr_status")
async def ibkr_status(current_user: CurrentUser, db: DBSession) -> dict:
    """Return whether the current user has the required IBKR credentials configured.

    Response example:
    {"paper_ready": true, "live_ready": false}
    """
    res = await db.execute(select(User).where(User.id == current_user.id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    paper_ready = bool(user.ibkr_paper_username and user.ibkr_paper_password and user.ibkr_paper_account_id)
    live_ready = bool(user.ibkr_live_username and user.ibkr_live_password and user.ibkr_live_account_id)

    return {"paper_ready": paper_ready, "live_ready": live_ready}

@router.patch("/ibkr_paper", response_model=UserRead)
async def update_ibkr_paper(current_user: CurrentUser, ibkr_paper_in: UserUpdateIbkrPaper, db: DBSession) -> UserRead:
    
    res = await db.execute(select(User).where(User.id == current_user.id))
    user = res.scalar_one_or_none()
    # user = await db.execute(select(User).where(User.id == current_user.id)) is same way to get the user
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.ibkr_paper_username = ibkr_paper_in.ibkr_paper_username
    user.ibkr_paper_password = ibkr_paper_in.ibkr_paper_password
    user.ibkr_paper_account_id = ibkr_paper_in.ibkr_paper_account_id
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/ibkr_live", response_model=UserRead)
async def update_ibkr_live(current_user: CurrentUser, ibkr_live_in: UserUpdateIbkrLive, db: DBSession) -> UserRead:
    
    res = await db.execute(select(User).where(User.id == current_user.id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.ibkr_live_username = ibkr_live_in.ibkr_live_username
    user.ibkr_live_password = ibkr_live_in.ibkr_live_password
    user.ibkr_live_account_id = ibkr_live_in.ibkr_live_account_id
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)

