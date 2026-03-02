import datetime

from pydantic import BaseModel, HttpUrl


class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LinkCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: str | None = None
    expires_at: datetime.datetime | None = None


class LinkUpdate(BaseModel):
    original_url: HttpUrl


class LinkResponse(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None

    model_config = {"from_attributes": True}


class LinkStats(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None = None
    click_count: int
    expires_at: datetime.datetime | None = None

    model_config = {"from_attributes": True}


class ExpiredLinkInfo(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    last_used_at: datetime.datetime | None = None
    click_count: int

    model_config = {"from_attributes": True}
