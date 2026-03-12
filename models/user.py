from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):
    email:    EmailStr
    name:     str = Field(..., min_length=1, max_length=100)
    role:     str = Field(default="operator", pattern="^(admin|operator|viewer)$")
    password: str = Field(..., min_length=8)


class UpdateUserRequest(BaseModel):
    name:   Optional[str] = Field(default=None, min_length=1, max_length=100)
    role:   Optional[str] = Field(default=None, pattern="^(admin|operator|viewer)$")
    active: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str
