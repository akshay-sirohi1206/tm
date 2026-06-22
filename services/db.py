import os
import uuid
import sqlite3
import logging
from contextlib import contextmanager
from typing import List, Optional

from fastapi import HTTPException

logger = logging.getLogger("BharatBot.db")
DB_PATH = os.getenv("DB_PATH", "bharatbot.db")

DDL = """
    CREATE TABLE IF NOT EXISTS users (
        user_id         TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        email           TEXT NOT NULL UNIQUE,
        password_hash   TEXT NOT NULL,
        created_at      DATETIME DEFAULT (datetime('now', 'utc')),
        updated_at      DATETIME DEFAULT (datetime('now', 'utc')),
        is_active       INTEGER DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

    CREATE TABLE IF NOT EXISTS refresh_tokens (
        jti             TEXT PRIMARY KEY,
        user_id         TEXT NOT NULL,
        token_hash      TEXT NOT NULL,
        expires_at      DATETIME NOT NULL,
        revoked         INTEGER DEFAULT 0,
        created_at      DATETIME DEFAULT (datetime('now', 'utc')),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens (user_id);

    CREATE TABLE IF NOT EXISTS sessions (
        session_id  TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        created_at  DATETIME DEFAULT (datetime('now', 'utc')),
        updated_at  DATETIME DEFAULT (datetime('now', 'utc')),
        title       TEXT,
        lang        TEXT DEFAULT 'en',
        is_active   INTEGER DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id, is_active, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions (updated_at DESC);

    CREATE TABLE IF NOT EXISTS messages (
        message_id    TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL,
        role          TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
        content_type  TEXT NOT NULL CHECK(content_type IN ('text', 'voice')),
        original_text TEXT,
        english_text  TEXT,
        response_text TEXT,
        detected_lang TEXT,
        audio_s3_uri  TEXT,
        has_audio_out INTEGER DEFAULT 0,
        created_at    DATETIME DEFAULT (datetime('now', 'utc')),
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id, created_at);
"""


@contextmanager
def get_db():
    """Yield a WAL-mode SQLite connection and auto-commit/rollback."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(DDL)
    logger.info("✅ SQLite tables verified / created.")


# ─── Row helpers ─────────────────────────────────────────────────────────────

def get_session_or_404(conn: sqlite3.Connection, session_id: str, user_id: Optional[str] = None) -> sqlite3.Row:
    """
    Fetch a session by ID. If user_id is provided, also verify ownership (for user-scoped routes).
    Raises 404 if not found or inactive.
    """
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ? AND is_active = 1", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if user_id and row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You don't have access to this session.")
    return row


def fetch_session_history(conn: sqlite3.Connection, session_id: str, limit: int = 20) -> List[dict]:
    rows = conn.execute(
        """
        SELECT role,
               COALESCE(english_text, original_text) AS content
        FROM   messages
        WHERE  session_id = ?
          AND  role IN ('user', 'assistant')
          AND  content IS NOT NULL
        ORDER  BY created_at DESC
        LIMIT  ?
        """,
        (session_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_assistant_message(
    conn: sqlite3.Connection, session_id: str, message_id: str
) -> sqlite3.Row:
    """
    Fetch a single assistant message row by (session_id, message_id).
    Raises 404 if not found or not an assistant message.
    """
    row = conn.execute(
        """
        SELECT * FROM messages
        WHERE  message_id = ?
          AND  session_id = ?
          AND  role       = 'assistant'
        """,
        (message_id, session_id),
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Message '{message_id}' not found in session '{session_id}'.",
        )
    return row


def save_turn(
    conn: sqlite3.Connection,
    session_id: str,
    content_type: str,
    original_text: str,
    english_text: str,
    response_text: str,
    detected_lang: str,
    audio_s3_uri: Optional[str] = None,
    has_audio_out: int = 0,
) -> None:
    now_expr = "datetime('now', 'utc')"

    user_id = uuid.uuid4().hex
    conn.execute(
        f"""
        INSERT INTO messages
            (message_id, session_id, role, content_type,
             original_text, english_text, detected_lang, audio_s3_uri)
        VALUES (?, ?, 'user', ?, ?, ?, ?, ?)
        """,
        (user_id, session_id, content_type, original_text, english_text,
         detected_lang, audio_s3_uri),
    )

    asst_id = uuid.uuid4().hex
    conn.execute(
        f"""
        INSERT INTO messages
            (message_id, session_id, role, content_type,
             original_text, english_text, response_text,
             detected_lang, has_audio_out)
        VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?)
        """,
        (asst_id, session_id, content_type, response_text, response_text,
         response_text, detected_lang, has_audio_out),
    )

    conn.execute(
        f"UPDATE sessions SET updated_at = {now_expr}, lang = ? WHERE session_id = ?",
        (detected_lang, session_id),
    )


# ─── User helpers ────────────────────────────────────────────────────────────

def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    """Fetch user by email, returns None if not found."""
    return conn.execute(
        "SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)
    ).fetchone()


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> Optional[sqlite3.Row]:
    """Fetch user by ID, returns None if not found."""
    return conn.execute(
        "SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,)
    ).fetchone()


def create_user(conn: sqlite3.Connection, name: str, email: str, password_hash: str) -> str:
    """Create a new user, return user_id."""
    user_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO users (user_id, name, email, password_hash)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, name, email, password_hash),
    )
    return user_id


def create_refresh_token(conn: sqlite3.Connection, user_id: str, token_hash: str, jti: str, expires_at: str) -> None:
    """Store a hashed refresh token."""
    conn.execute(
        """
        INSERT INTO refresh_tokens (jti, user_id, token_hash, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (jti, user_id, token_hash, expires_at),
    )


def get_refresh_token(conn: sqlite3.Connection, jti: str) -> Optional[sqlite3.Row]:
    """Fetch refresh token by jti."""
    return conn.execute(
        "SELECT * FROM refresh_tokens WHERE jti = ?", (jti,)
    ).fetchone()


def revoke_refresh_token(conn: sqlite3.Connection, jti: str) -> None:
    """Mark a refresh token as revoked."""
    conn.execute(
        "UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?", (jti,)
    )


def revoke_all_refresh_tokens(conn: sqlite3.Connection, user_id: str) -> None:
    """Revoke all refresh tokens for a user (e.g., on password change)."""
    conn.execute(
        "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (user_id,)
    )


def update_user_password(conn: sqlite3.Connection, user_id: str, password_hash: str) -> None:
    """Update user password hash and revoke all existing refresh tokens."""
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now', 'utc') WHERE user_id = ?",
        (password_hash, user_id),
    )
    revoke_all_refresh_tokens(conn, user_id)
