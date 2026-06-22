from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
import re


# ─── Auth Models ─────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    created_at: str
    is_active: bool


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ─── Session Models ──────────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    lang: Optional[str] = "en"


class SessionUpdateRequest(BaseModel):
    title: Optional[str] = None
    lang: Optional[str] = None


# ─── Password Validator (reusable) ────────────────────────────────────────────

def validate_password(password: str, name: Optional[str] = None, email: Optional[str] = None) -> list[str]:
    """
    Validate password against policy. Returns list of violation messages (empty if valid).
    Policy:
      - Min 8 chars
      - At least one uppercase, lowercase, digit, special char
      - No leading/trailing whitespace
      - Not equal to email or name
    """
    errors = []

    if not password or len(password) < 8:
        errors.append("Password must be at least 8 characters long")

    if password != password.strip():
        errors.append("Password cannot have leading or trailing whitespace")

    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")

    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        errors.append("Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)")

    if email and password.lower() == email.lower():
        errors.append("Password cannot be the same as your email")

    if name and password.lower() == name.lower():
        errors.append("Password cannot be the same as your name")

    return errors
