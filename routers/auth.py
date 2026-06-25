"""
Authentication routes: signup, login, refresh, logout, me, change-password mapped to MySQL RDS.
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
    """Register a new user inside RDS cluster."""
    pwd_errors = validate_password(body.password, name=body.name, email=body.email)
    if pwd_errors:
        return error_response(
            code="INVALID_PASSWORD",
            message="; ".join(pwd_errors),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    with get_db() as conn:
        existing = get_user_by_email(conn, body.email)
        if existing:
            return error_response(
                code="EMAIL_ALREADY_EXISTS",
                message="A user with this email already exists.",
                status_code=status.HTTP_409_CONFLICT
            )

        hashed = hash_password(body.password)
        user_id = create_user(conn, body.name, body.email, hashed)

        access_token = issue_access_token(user_id)
        refresh_token, jti, exp_str = issue_refresh_token(user_id)
        
        create_refresh_token(conn, user_id, hash_token(refresh_token), jti, exp_str)

    logger.info(f"[AUTH] Signed up user: {user_id} ({body.email})")
    return success_response(
        data={
            "user": {"user_id": user_id, "name": body.name, "email": body.email},
            "tokens": {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}
        },
        status_code=201
    )


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate and fetch standard active tokens."""
    with get_db() as conn:
        user = get_user_by_email(conn, body.email)
        if not user or not verify_password(body.password, user["password_hash"]):
            return error_response(
                code="INVALID_CREDENTIALS",
                message="Incorrect email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        user_id = user["user_id"]
        access_token = issue_access_token(user_id, user["email"])
        refresh_token, jti, exp_str = issue_refresh_token(user_id)
        
        create_refresh_token(conn, user_id, hash_token(refresh_token), jti, exp_str)

    logger.info(f"[AUTH] Logged in user: {user_id}")
    return success_response(
        data={
            "user": {
                "user_id": user["user_id"],
                "name": user["name"],
                "email": user["email"],
            },
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
    )


@router.post("/refresh")
async def refresh(body: RefreshTokenRequest):
    """Exchange refresh token securely."""
    payload = verify_refresh_token(body.refresh_token)
    jti = payload.get("jti")
    user_id = payload.get("sub")

    if not jti or not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token payload.")

    with get_db() as conn:
        stored = get_refresh_token(conn, jti)
        if not stored or stored["revoked"] or stored["user_id"] != user_id:
            raise HTTPException(status_code=401, detail="Refresh token is invalid or revoked.")

        if not verify_password(body.refresh_token, stored["token_hash"]):
            raise HTTPException(status_code=401, detail="Invalid token token context.")

        # ✅ user fetch karo taaki email mile
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        access_token = issue_access_token(user_id, user["email"])
        new_refresh_token, new_jti, exp_str = issue_refresh_token(user_id)

        revoke_refresh_token(conn, jti)
        create_refresh_token(conn, user_id, hash_token(new_refresh_token), new_jti, exp_str)

    return success_response(
        data={"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}
    )
    


@router.post("/logout", status_code=200)
async def logout(body: RefreshTokenRequest, user_id: str = Depends(get_current_user)):
    """Invalidate token context instantly."""
    payload = verify_refresh_token(body.refresh_token)
    jti = payload.get("jti")
    if jti:
        with get_db() as conn:
            revoke_refresh_token(conn, jti)
    logger.info(f"[AUTH] Logged out session jti: {jti}")
    return success_response(data={"message": "Logged out successfully."})


@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user)):
    """Fetch current session owner information."""
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User profile metadata missing.")
    return success_response(
        data={"user_id": user["user_id"], "name": user["name"], "email": user["email"]}
    )


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user_id: str = Depends(get_current_user)):
    """Process explicit secure profile updates."""
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        if not verify_password(body.current_password, user["password_hash"]):
            return error_response(
                code="INVALID_CURRENT_PASSWORD",
                message="Current password is incorrect.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        pwd_errors = validate_password(body.new_password, name=user["name"], email=user["email"])
        if pwd_errors:
            return error_response(
                code="INVALID_NEW_PASSWORD",
                message="; ".join(pwd_errors),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        new_password_hash = hash_password(body.new_password)
        update_user_password(conn, user_id, new_password_hash)

    logger.info(f"[AUTH] Password changed for target user: {user_id}")
    return success_response(message="Password updated successfully. Other endpoints logged out.")