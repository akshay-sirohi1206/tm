import uuid
import logging

from fastapi import APIRouter, Depends

from models.schemas import SessionCreateRequest, SessionUpdateRequest
from core.security import get_current_user
from core.responses import success_response, error_response
from services.db import get_db, get_session_or_404

logger = logging.getLogger("BharatBot.sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(get_current_user)])


@router.post("", status_code=201)
async def create_session(body: SessionCreateRequest, user_id: str = Depends(get_current_user)):
    """Create a new chat session for the authenticated user in AWS RDS."""
    session_id = uuid.uuid4().hex
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sessions (session_id, user_id, title, lang) VALUES (%s, %s, %s, %s)",
                (session_id, user_id, body.title, body.lang or "en"),
            )
    logger.info(f"[SESSION] Created: {session_id!r} user={user_id!r} title={body.title!r}")
    return success_response(
        data={"session_id": session_id, "title": body.title, "lang": body.lang or "en"},
        status_code=201,
    )


@router.get("")
async def list_sessions(user_id: str = Depends(get_current_user), limit: int = 20, offset: int = 0):
    """List all sessions for the authenticated user from RDS."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT session_id, user_id, title, lang, is_active, created_at, updated_at 
                FROM sessions 
                WHERE user_id = %s AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset),
            )
            rows = cursor.fetchall()

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM sessions WHERE user_id = %s AND is_active = 1",
                (user_id,),
            )
            total = cursor.fetchone()["cnt"]

    return success_response(data={"total": total, "limit": limit, "offset": offset, "sessions": rows})


@router.get("/{session_id}/messages")
async def list_session_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """Fetch all messages for a specific session."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT message_id, role, content_type, original_text,
                       response_text, detected_lang, has_audio_out, created_at
                FROM   messages
                WHERE  session_id = %s
                ORDER  BY created_at ASC
                LIMIT  %s OFFSET %s
                """,
                (session_id, limit, offset),
            )
            rows = cursor.fetchall()

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE session_id = %s", (session_id,)
            )
            total = cursor.fetchone()["cnt"]

    return success_response(
        data={
            "session_id": session_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages": rows,
        }
    )


@router.delete("/{session_id}/messages", status_code=204)
async def clear_session_messages(session_id: str, user_id: str = Depends(get_current_user)):
    """Clear all messages in a session with MySQL auto-commit block integration."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            cursor.execute(
                "UPDATE sessions SET updated_at = NOW() WHERE session_id = %s",
                (session_id,),
            )
    return None

