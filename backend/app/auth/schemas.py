from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from steel_core.db.enums import Role


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    must_change_password: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
