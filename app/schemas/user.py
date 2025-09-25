from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str
    username: str


class UserLogin(UserBase):
    password: str


class UserRead(UserBase):
    id: str
    is_active: bool
    username: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserUpdateIbkrPaper(BaseModel):
    ibkr_paper_username: str
    ibkr_paper_password: str
    ibkr_paper_account_id: str

class UserUpdateIbkrLive(BaseModel):
    ibkr_live_username: str
    ibkr_live_password: str
    ibkr_live_account_id: str
