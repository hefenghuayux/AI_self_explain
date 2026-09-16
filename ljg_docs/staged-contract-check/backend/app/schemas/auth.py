from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Password = Annotated[str, StringConstraints(min_length=6)]


class RegisterInput(BaseModel):
    username: Username
    password: Password
    full_name: FullName = Field(alias="fullName")


class LoginInput(BaseModel):
    username: Username
    password: str
    remember_login: bool = Field(default=False, alias="rememberLogin")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    username: str
    full_name: str = Field(serialization_alias="fullName")
    role: Literal["STUDENT", "TEACHER"]


class AuthResponse(BaseModel):
    token: str
    expires_at: datetime = Field(serialization_alias="expiresAt")
    user: UserResponse
