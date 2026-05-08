import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import BaseSchema


class UserOut(BaseSchema):
    id: int
    username: str
    is_active: bool
    email: str | None = None
    role: str
    created_at: datetime
    help_pages_seen: list[str] = []
    pending_email: str | None = None

    @field_validator("help_pages_seen", mode="before")
    @classmethod
    def parse_help_pages(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return json.loads(v)
        return v


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = "dj"


class AdminUserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


class AdminUserOut(BaseSchema):
    id: int
    username: str
    is_active: bool
    role: str
    created_at: datetime
    event_count: int = 0


class AdminEventOut(BaseSchema):
    id: int
    code: str
    name: str
    owner_username: str
    owner_id: int
    created_at: datetime
    expires_at: datetime
    is_active: bool
    request_count: int = 0


class SystemStats(BaseModel):
    total_users: int
    active_users: int
    pending_users: int
    total_events: int
    active_events: int
    total_requests: int


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    limit: int


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str
    turnstile_token: str = Field("", max_length=4096)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            msg = "Username must contain only letters, numbers, and underscores"
            raise ValueError(msg)
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            msg = "Passwords do not match"
            raise ValueError(msg)
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_new_password: str

    @field_validator("confirm_new_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class RequestEmailChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_email: EmailStr


class PublicSettings(BaseModel):
    registration_enabled: bool
    turnstile_site_key: str


class HelpPageSeenRequest(BaseModel):
    page: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
