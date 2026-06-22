"""
Authentication routes: signup, login, refresh, logout, me, change-password.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import EmailStr

from models.schemas import (
    SignupRequest, LoginRequest, ChangePasswordRequest, TokenResponse,
    UserResponse, RefreshTokenRequest, validate_password
)
from core.security import (
    hash_password, verify_password, hash_token,
    issue_access_token, issue_refresh_token, verify_refresh_token,
    get_current_user
)
from core.responses import success_response, error_response
from services.db import (
    get_db, get_user_by_email, get_user_by_id, create_user,
    create_refresh_token, get_refresh_token, revoke_refresh_token,
    update_user_password
)

logger = logging.getLogger("BharatBot.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest):
    """
    Register a new user. Validates email uniqueness and password policy.
    Returns new user + auto-login tokens (access + refresh).
    """
    # ── Validate password policy ─────────────────────────────────────────
    pwd_errors = validate_password(body.password, name=body.name, email=body.email)
    if pwd_errors:
        return error_response(
            code="INVALID_PASSWORD",
            message="; ".join(pwd_errors),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # ── Check email uniqueness ───────────────────────────────────────────
    with get_db() as conn:
        if get_user_by_email(conn, body.email):
            return error_response(
                code="EMAIL_ALREADY_EXISTS",
                message=f"Email '{body.email}' is already registered.",
                status_code=status.HTTP_409_CONFLICT,
            )

        # ── Create user ──────────────────────────────────────────────────
        password_hash = hash_password(body.password)
        user_id = create_user(conn, body.name, body.email, password_hash)

        # ── Issue tokens (auto-login) ────────────────────────────────────
        access_token = issue_access_token(user_id, body.email)
        refresh_token, jti, expires_at = issue_refresh_token(user_id)

        # ── Store refresh token hash ─────────────────────────────────────
        token_hash = hash_token(refresh_token)
        create_refresh_token(conn, user_id, token_hash, jti, expires_at)

    logger.info(f"[AUTH] User created: {user_id} ({body.email})")

    return success_response(
        data={
            "user": {
                "user_id": user_id,
                "name": body.name,
                "email": body.email,
            },
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        },
        status_code=201,
    )


@router.post("/login")
async def login(body: LoginRequest):
    """
    Authenticate user by email + password.
    Returns access + refresh tokens on success.
    """
    with get_db() as conn:
        user = get_user_by_email(conn, body.email)
        if not user or not verify_password(body.password, user["password_hash"]):
            # Generic error — don't leak whether email exists
            return error_response(
                code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        user_id = user["user_id"]

        # ── Issue tokens ─────────────────────────────────────────────────
        access_token = issue_access_token(user_id, user["email"])
        refresh_token, jti, expires_at = issue_refresh_token(user_id)

        # ── Store refresh token hash ─────────────────────────────────────
        token_hash = hash_token(refresh_token)
        create_refresh_token(conn, user_id, token_hash, jti, expires_at)

    logger.info(f"[AUTH] Login successful: {user_id} ({body.email})")

    return success_response(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
    )


@router.post("/refresh")
async def refresh(body: RefreshTokenRequest):
    """
    Exchange a refresh token for a new access token (and optionally a new refresh token).
    Rotates refresh token for security.
    """
    try:
        payload = verify_refresh_token(body.refresh_token)
    except ValueError as exc:
        return error_response(
            code="INVALID_REFRESH_TOKEN",
            message=f"Refresh token is invalid or expired: {exc}",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    # ── Check if refresh token is revoked in DB ──────────────────────────
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            return error_response(
                code="USER_NOT_FOUND",
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rt_row = get_refresh_token(conn, jti)
        if not rt_row or rt_row["revoked"]:
            return error_response(
                code="REFRESH_TOKEN_REVOKED",
                message="Refresh token has been revoked.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # ── Issue new access token + rotate refresh token ──────────────────
        access_token = issue_access_token(user_id, user["email"])
        new_refresh_token, new_jti, new_expires_at = issue_refresh_token(user_id)

        # ── Revoke old refresh token ─────────────────────────────────────
        revoke_refresh_token(conn, jti)

        # ── Store new refresh token hash ─────────────────────────────────
        new_token_hash = hash_token(new_refresh_token)
        create_refresh_token(conn, user_id, new_token_hash, new_jti, new_expires_at)

    logger.info(f"[AUTH] Token refreshed: {user_id}")

    return success_response(
        data={
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
        }
    )


@router.get("/me")
async def get_profile(user_id: str = Depends(get_current_user)):
    """
    Get authenticated user's profile.
    """
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

    return success_response(
        data={
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "created_at": user["created_at"],
            "is_active": bool(user["is_active"]),
        }
    )


@router.post("/logout")
async def logout(body: RefreshTokenRequest, user_id: str = Depends(get_current_user)):
    """
    Revoke a refresh token (logout).
    """
    try:
        payload = verify_refresh_token(body.refresh_token)
    except ValueError:
        return error_response(
            code="INVALID_REFRESH_TOKEN",
            message="Invalid refresh token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    jti = payload.get("jti")
    token_user_id = payload.get("sub")

    # Verify ownership
    if token_user_id != user_id:
        return error_response(
            code="FORBIDDEN",
            message="Cannot revoke another user's token.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    with get_db() as conn:
        revoke_refresh_token(conn, jti)

    logger.info(f"[AUTH] Logout successful: {user_id}")

    return success_response(data={"message": "Logged out successfully."})


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user_id: str = Depends(get_current_user)):
    """
    Change user password. Requires current password + new password.
    Revokes all existing refresh tokens on success (other sessions logged out).
    """
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        # ── Verify current password ──────────────────────────────────────
        if not verify_password(body.current_password, user["password_hash"]):
            return error_response(
                code="INVALID_CURRENT_PASSWORD",
                message="Current password is incorrect.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # ── Validate new password policy ─────────────────────────────────
        pwd_errors = validate_password(body.new_password, name=user["name"], email=user["email"])
        if pwd_errors:
            return error_response(
                code="INVALID_NEW_PASSWORD",
                message="; ".join(pwd_errors),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # ── Update password (also revokes all refresh tokens) ─────────────
        new_password_hash = hash_password(body.new_password)
        update_user_password(conn, user_id, new_password_hash)

    logger.info(f"[AUTH] Password changed: {user_id}")

    return success_response(
        data={"message": "Password changed successfully. All other sessions have been logged out."}
    )
