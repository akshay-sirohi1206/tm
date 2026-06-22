"""
Security utilities: password hashing, JWT token issue/verify, authentication dependency.
"""

import os
import logging
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer

logger = logging.getLogger("BharatBot.security")

# ─── Config from environment ────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ─── Password Hashing ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ─── Token Hashing (for refresh token storage) ──────────────────────────────

def hash_token(token: str) -> str:
    """Hash a token for storage in DB (not reversible)."""
    return hashlib.sha256(token.encode()).hexdigest()


# ─── JWT Token Issue ────────────────────────────────────────────────────────

def issue_access_token(user_id: str, email: str) -> str:
    """Issue a short-lived access token."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": expires,
        "iat": now,
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def issue_refresh_token(user_id: str) -> tuple[str, str, str]:
    """
    Issue a long-lived refresh token.
    Returns: (token, jti, expires_at_iso)
    """
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    expires = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "exp": expires,
        "iat": now,
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    expires_at_iso = expires.isoformat()

    return token, jti, expires_at_iso


# ─── JWT Token Verification ────────────────────────────────────────────────

def verify_token(token: str) -> dict:
    """
    Verify and decode a JWT token.
    Raises ValueError if invalid, expired, or malformed.
    Returns payload dict.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}")


def verify_access_token(token: str) -> dict:
    """
    Verify that token is a valid access token.
    Raises ValueError if not an access token.
    """
    payload = verify_token(token)
    if payload.get("type") != "access":
        raise ValueError("Token is not an access token")
    return payload


def verify_refresh_token(token: str) -> dict:
    """
    Verify that token is a valid refresh token.
    Raises ValueError if not a refresh token.
    """
    payload = verify_token(token)
    if payload.get("type") != "refresh":
        raise ValueError("Token is not a refresh token")
    return payload


# ─── FastAPI Dependency ─────────────────────────────────────────────────────

oauth2_scheme = HTTPBearer()


def get_current_user(credentials = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency that extracts and validates the access token from the
    Authorization: Bearer header. Returns user_id on success, raises 401 on failure.
    """
    token = credentials.credentials
    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing 'sub' (user_id)")
        return user_id
    except (ValueError, KeyError) as exc:
        logger.warning(f"Invalid access token: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── WebSocket Token Validation ─────────────────────────────────────────────

async def verify_ws_token(token: str) -> str:
    """
    Verify a token from WebSocket query param. Returns user_id on success.
    Raises HTTPException with 4401 status if invalid.
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing 'sub' (user_id)")
        return user_id
    except (ValueError, KeyError) as exc:
        logger.warning(f"Invalid WebSocket token: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
