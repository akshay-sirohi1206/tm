import os
import uuid
import pymysql
import logging
from contextlib import contextmanager
from typing import List, Optional

from fastapi import HTTPException

logger = logging.getLogger("BharatBot.db")

# AWS Task definition se direct MySQL URL milega, local fallback ke liye standard mysql string rakh di hai
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "mysql+pymysql://bharatbot_admin:SecureDbPass2026!@terraform-20260623161812694500000002.cd6264mcmeo4.us-east-1.rds.amazonaws.com:3306/bharatbotdb"
)

def parse_mysql_url(url: str):
    """Parse standard database connection string into pymysql parameters."""
    try:
        # Removing driver prefix if present
        if url.startswith("mysql+pymysql://"):
            clean_url = url.replace("mysql+pymysql://", "")
        else:
            clean_url = url.replace("mysql://", "")
            
        auth, rest = clean_url.split("@")
        user, password = auth.split(":")
        host_port, db_name = rest.split("/")
        
        if ":" in host_port:
            host, port = host_port.split(":")
            port = int(port)
        else:
            host = host_port
            port = 3306
            
        # Strip query parameters if any (e.g. ?charset=utf8mb4)
        if "?" in db_name:
            db_name = db_name.split("?")[0]
            
        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": db_name,
            "cursorclass": pymysql.cursors.DictCursor
        }
    except Exception as e:
        logger.error(f"❌ Failed to parse DATABASE_URL: {e}")
        raise RuntimeError("Invalid DATABASE_URL config format.")

# Connection params config compilation
DB_CONFIG = parse_mysql_url(DATABASE_URL)

# MySQL specific DDL structure adjustments (TEXT to VARCHAR index scaling, datetime mapping)
DDL = """
    CREATE TABLE IF NOT EXISTS users (
        user_id         VARCHAR(36) PRIMARY KEY,
        name            VARCHAR(255) NOT NULL,
        email           VARCHAR(255) NOT NULL UNIQUE,
        password_hash   VARCHAR(255) NOT NULL,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_active       INT DEFAULT 1
    );
"""

DDL_INDEX_1 = "CREATE INDEX idx_users_email ON users (email);"

DDL_REFRESH = """
    CREATE TABLE IF NOT EXISTS refresh_tokens (
        jti             VARCHAR(36) PRIMARY KEY,
        user_id         VARCHAR(36) NOT NULL,
        token_hash      VARCHAR(255) NOT NULL,
        expires_at      DATETIME NOT NULL,
        revoked         INT DEFAULT 0,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
"""
DDL_INDEX_2 = "CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens (user_id);"

DDL_SESSIONS = """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id  VARCHAR(36) PRIMARY KEY,
        user_id     VARCHAR(36) NOT NULL,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        title       VARCHAR(255),
        lang        VARCHAR(10) DEFAULT 'en',
        is_active   INT DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
"""
DDL_INDEX_3 = "CREATE INDEX idx_sessions_user_id ON sessions (user_id, is_active, updated_at DESC);"
DDL_INDEX_4 = "CREATE INDEX idx_sessions_updated_at ON sessions (updated_at DESC);"

DDL_MESSAGES = """
    CREATE TABLE IF NOT EXISTS messages (
        message_id    VARCHAR(36) PRIMARY KEY,
        session_id    VARCHAR(36) NOT NULL,
        role          VARCHAR(20) NOT NULL CHECK(role IN ('user', 'assistant')),
        content_type  VARCHAR(20) NOT NULL CHECK(content_type IN ('text', 'voice')),
        original_text TEXT,
        english_text  TEXT,
        response_text TEXT,
        detected_lang VARCHAR(10),
        audio_s3_uri  VARCHAR(512),
        has_audio_out INT DEFAULT 0,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    );
"""
DDL_INDEX_5 = "CREATE INDEX idx_messages_session_id ON messages (session_id, created_at);"


@contextmanager
def get_db():
    """Yield a dynamic PyMySQL connection with operational auto-commit block context."""
    conn = pymysql.connect(**DB_CONFIG)
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
        with conn.cursor() as cursor:
            # Running statements safely individually inside MySQL pipeline execution context
            cursor.execute(DDL)
            try:
                cursor.execute(DDL_INDEX_1)
            except Exception: pass # Skip if index already exists
            
            cursor.execute(DDL_REFRESH)
            try:
                cursor.execute(DDL_INDEX_2)
            except Exception: pass
            
            cursor.execute(DDL_SESSIONS)
            try:
                cursor.execute(DDL_INDEX_3)
                cursor.execute(DDL_INDEX_4)
            except Exception: pass
            
            cursor.execute(DDL_MESSAGES)
            try:
                cursor.execute(DDL_INDEX_5)
            except Exception: pass
            
    logger.info("✅ Remote AWS RDS MySQL database schema tables verified / initialized.")


# ─── Row helpers ─────────────────────────────────────────────────────────────

def get_session_or_404(conn: pymysql.Connection, session_id: str, user_id: Optional[str] = None) -> dict:
    """Fetch a session from RDS MySQL by ID. Raises 404/403 if conditions fail."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM sessions WHERE session_id = %s AND is_active = 1", (session_id,)
        )
        row = cursor.fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if user_id and row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You don't have access to this session.")
    return row


def fetch_session_history(conn: pymysql.Connection, session_id: str, limit: int = 20) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT role,
                   COALESCE(english_text, original_text) AS content
            FROM   messages
            WHERE  session_id = %s
              AND  role IN ('user', 'assistant')
              AND  content IS NOT NULL
            ORDER  BY created_at DESC
            LIMIT  %s
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_assistant_message(
    conn: pymysql.Connection, session_id: str, message_id: str
) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT * FROM messages
            WHERE  message_id = %s
              AND  session_id = %s
              AND  role       = 'assistant'
            """,
            (message_id, session_id),
        )
        row = cursor.fetchone()
        
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Message '{message_id}' not found in session '{session_id}'.",
        )
    return row


def save_turn(
    conn: pymysql.Connection,
    session_id: str,
    content_type: str,
    original_text: str,
    english_text: str,
    response_text: str,
    detected_lang: str,
    audio_s3_uri: Optional[str] = None,
    has_audio_out: int = 0,
) -> None:
    user_id = uuid.uuid4().hex
    asst_id = uuid.uuid4().hex

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO messages
                (message_id, session_id, role, content_type,
                 original_text, english_text, detected_lang, audio_s3_uri)
            VALUES (%s, %s, 'user', %s, %s, %s, %s, %s)
            """,
            (user_id, session_id, content_type, original_text, english_text,
             detected_lang, audio_s3_uri),
        )

        cursor.execute(
            """
            INSERT INTO messages
                (message_id, session_id, role, content_type,
                 original_text, english_text, response_text,
                 detected_lang, has_audio_out)
            VALUES (%s, %s, 'assistant', %s, %s, %s, %s, %s, %s)
            """,
            (asst_id, session_id, content_type, response_text, response_text,
             response_text, detected_lang, has_audio_out),
        )

        cursor.execute(
            "UPDATE sessions SET updated_at = NOW(), lang = %s WHERE session_id = %s",
            (detected_lang, session_id),
        )


# ─── User helpers ────────────────────────────────────────────────────────────

def get_user_by_email(conn: pymysql.Connection, email: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE email = %s AND is_active = 1", (email,)
        )
        return cursor.fetchone()


def get_user_by_id(conn: pymysql.Connection, user_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE user_id = %s AND is_active = 1", (user_id,)
        )
        return cursor.fetchone()


def create_user(conn: pymysql.Connection, name: str, email: str, password_hash: str) -> str:
    user_id = uuid.uuid4().hex
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (user_id, name, email, password_hash)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, name, email, password_hash),
        )
    return user_id


def create_refresh_token(conn: pymysql.Connection, user_id: str, token_hash: str, jti: str, expires_at: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO refresh_tokens (jti, user_id, token_hash, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (jti, user_id, token_hash, expires_at),
        )


def get_refresh_token(conn: pymysql.Connection, jti: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM refresh_tokens WHERE jti = %s", (jti,)
        )
        return cursor.fetchone()


def revoke_refresh_token(conn: pymysql.Connection, jti: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE jti = %s", (jti,)
        )


def revoke_all_refresh_tokens(conn: pymysql.Connection, user_id: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = %s", (user_id,)
        )


def update_user_password(conn: pymysql.Connection, user_id: str, password_hash: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE user_id = %s",
            (password_hash, user_id),
        )
    revoke_all_refresh_tokens(conn, user_id)
    