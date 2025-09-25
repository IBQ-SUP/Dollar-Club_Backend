import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    get_user_from_token,
)
from app.core.config import settings
from authlib.integrations.starlette_client import OAuth
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserRead


router = APIRouter()

oauth = OAuth()
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@router.post("/register")
async def register(user_in: UserCreate, db: DBSession):
    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        id=str(uuid.uuid4()),
        email=user_in.email,
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        ibkr_paper_username="",
        ibkr_paper_password="",
        ibkr_paper_account_id="",
        ibkr_live_username="",
        ibkr_live_password="",
        ibkr_live_account_id="",
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Issue JWT and set as HttpOnly cookie
    token = create_access_token(subject=user.email)
    refresh = create_refresh_token(subject=user.email)
    payload = {
        "access_token": token,
        "refresh_token": refresh,
        "user": UserRead.model_validate(user).model_dump(),
    }
    response = JSONResponse(content=payload)
    # Adjust secure flag based on environment/proxy
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response


@router.post("/login")
async def login(user_in: UserLogin, db: DBSession):
    res = await db.execute(select(User).where(User.email == user_in.email))
    user = res.scalar_one_or_none()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=user.email)
    refresh = create_refresh_token(subject=user.email)
    payload = {
        "access_token": token,
        "refresh_token": refresh,
        "user": UserRead.model_validate(user).model_dump(),
    }
    response = JSONResponse(content=payload)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response


@router.get("/me")
async def read_me(
    db: DBSession,
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    token = access_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await get_user_from_token(token, db)  # type: ignore[arg-type]
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return UserRead.model_validate(user)


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"detail": "Logged out"})
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return response


@router.post("/refresh")
async def refresh_token(
    db: DBSession,
    refresh_token: str | None = Cookie(default=None),
):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    # Validate refresh token and subject
    user = await get_user_from_token(refresh_token, db)  # type: ignore[arg-type]
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    # Create new access token
    new_access = create_access_token(subject=user.email)
    response = JSONResponse(content={"access_token": new_access})
    response.set_cookie(
        key="access_token",
        value=new_access,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response


@router.get("/google/login")
async def google_login(request: Request, next: str | None = None):
    if not hasattr(oauth, "google"):  # pragma: no cover - misconfigured env
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    redirect_uri = settings.GOOGLE_REDIRECT_URI or str(request.url_for("google_callback"))
    request.session["next"] = next or settings.FRONTEND_URL
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: DBSession):
    try:
        if not hasattr(oauth, "google"):  # pragma: no cover
            raise HTTPException(status_code=500, detail="Google OAuth not configured")
        print("google_callback")
        print(request)
        print(db)
        token = await oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            # Fallback: fetch from userinfo endpoint
            resp = await oauth.google.get("userinfo", token=token)
            userinfo = resp.json()
        email = userinfo.get("email")
        name = userinfo.get("name") or email
        if not email:
            raise HTTPException(status_code=400, detail="Google account has no email")

        # Upsert user
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if not user:
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                username=name,
                hashed_password=get_password_hash(uuid.uuid4().hex),
                ibkr_paper_username="",
                ibkr_paper_password="",
                ibkr_paper_account_id="",
                ibkr_live_username="",
                ibkr_live_password="",
                ibkr_live_account_id="",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        jwt_token = create_access_token(subject=user.email)
        response = RedirectResponse(url=request.session.pop("next", settings.FRONTEND_URL))
        response.set_cookie(
            key="access_token",
            value=jwt_token,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return response
    except Exception as e:
        print(e)
    finally:
        print("finally")
