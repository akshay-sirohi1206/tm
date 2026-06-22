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
    """Create a new chat session for the authenticated user."""
    session_id = uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, title, lang) VALUES (?, ?, ?, ?)",
            (session_id, user_id, body.title, body.lang or "en"),
        )
    logger.info(f"[SESSION] Created: {session_id!r} user={user_id!r} title={body.title!r}")
    return success_response(
        data={"session_id": session_id, "title": body.title, "lang": body.lang or "en"},
        status_code=201,
    )


@router.get("")
async def list_sessions(user_id: str = Depends(get_current_user), limit: int = 20, offset: int = 0):
    """List all sessions for the authenticated user."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.session_id, s.title, s.lang, s.created_at, s.updated_at,
                   COUNT(m.message_id) AS message_count
            FROM   sessions s
            LEFT JOIN messages m ON m.session_id = s.session_id
            WHERE  s.user_id = ? AND s.is_active = 1
            GROUP  BY s.session_id
            ORDER  BY s.updated_at DESC
            LIMIT  ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
    return success_response(
        data={
            "sessions": [dict(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }
    )


@router.get("/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(get_current_user)):
    """Get a specific session (with ownership verification)."""
    with get_db() as conn:
        row = get_session_or_404(conn, session_id, user_id=user_id)
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
    return success_response(
        data={**dict(row), "message_count": msg_count}
    )


@router.patch("/{session_id}")
async def update_session(session_id: str, body: SessionUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update a session (with ownership verification)."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        if body.title is not None:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = datetime('now','utc') WHERE session_id = ?",
                (body.title, session_id),
            )
        if body.lang is not None:
            conn.execute(
                "UPDATE sessions SET lang = ?, updated_at = datetime('now','utc') WHERE session_id = ?",
                (body.lang, session_id),
            )
    return success_response(
        data={"session_id": session_id, "updated": True}
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: str = Depends(get_current_user)):
    """Soft-delete a session (with ownership verification)."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        conn.execute(
            "UPDATE sessions SET is_active = 0, updated_at = datetime('now','utc') WHERE session_id = ?",
            (session_id,),
        )
    logger.info(f"[SESSION] Soft-deleted: {session_id!r} user={user_id!r}")


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """Get all messages in a session (with ownership verification)."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        rows = conn.execute(
            """
            SELECT message_id, role, content_type, original_text,
                   response_text, detected_lang, has_audio_out, created_at
            FROM   messages
            WHERE  session_id = ?
            ORDER  BY created_at ASC
            LIMIT  ? OFFSET ?
            """,
            (session_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
    return success_response(
        data={
            "session_id": session_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages": [dict(r) for r in rows],
        }
    )


@router.delete("/{session_id}/messages", status_code=204)
async def clear_session_messages(session_id: str, user_id: str = Depends(get_current_user)):
    """Clear all messages in a session (with ownership verification)."""
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute(
            "UPDATE sessions SET updated_at = datetime('now','utc') WHERE session_id = ?",
            (session_id,),
        )
    logger.info(f"[SESSION] Cleared messages for session: {session_id!r} user={user_id!r}")
