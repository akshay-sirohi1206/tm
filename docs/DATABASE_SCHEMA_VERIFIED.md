# Database Schema - VERIFIED ✅

**Last Updated:** 2026-06-21 22:19 IST  
**Status:** ✅ ALL TABLES CREATED  
**Method:** Alembic Migration Applied  

---

## Summary

| Table | Columns | Primary Key | Foreign Keys | Status |
|-------|---------|-------------|--------------|--------|
| **users** | 7 | user_id | - | ✅ |
| **refresh_tokens** | 6 | jti | user_id → users | ✅ |
| **sessions** | 7 | session_id | user_id → users | ✅ |
| **messages** | 11 | message_id | session_id → sessions | ✅ |
| **alembic_version** | 1 | version_num | - | ✅ |

**Total Columns:** 31 (+ 1 system table)

---

## Table Details

### 1. USERS Table (7 columns)
```
user_id         VARCHAR(32)    PRIMARY KEY, NOT NULL
name            VARCHAR        NOT NULL
email           VARCHAR        NOT NULL, UNIQUE INDEX
password_hash   VARCHAR        NOT NULL
created_at      DATETIME       AUTO DEFAULT
updated_at      DATETIME       AUTO DEFAULT
is_active       BOOLEAN        DEFAULT TRUE
```

**Purpose:** User authentication and profile storage

---

### 2. REFRESH_TOKENS Table (6 columns)
```
jti             VARCHAR(255)   PRIMARY KEY, NOT NULL
user_id         VARCHAR(32)    NOT NULL, FK → users.user_id
token_hash      VARCHAR        NOT NULL
expires_at      DATETIME       NOT NULL
revoked         BOOLEAN        DEFAULT FALSE
created_at      DATETIME       AUTO DEFAULT
```

**Purpose:** Secure JWT refresh token storage

---

### 3. SESSIONS Table (7 columns)
```
session_id      VARCHAR(32)    PRIMARY KEY, NOT NULL
user_id         VARCHAR(32)    NOT NULL, FK → users.user_id
created_at      DATETIME       AUTO DEFAULT
updated_at      DATETIME       AUTO DEFAULT
title           VARCHAR        NULLABLE
lang            VARCHAR        DEFAULT 'en'
is_active       BOOLEAN        DEFAULT TRUE
```

**Constraints:**
- CHECK: lang IN ('en', 'hi', 'ta', 'te', 'mr', 'gu', 'kn', 'ml', 'pa', 'bn')

**Purpose:** Chat session storage per user

---

### 4. MESSAGES Table (11 columns)
```
message_id      VARCHAR(32)    PRIMARY KEY, NOT NULL
session_id      VARCHAR(32)    NOT NULL, FK → sessions.session_id
role            VARCHAR(10)    NOT NULL
content_type    VARCHAR(10)    NOT NULL
original_text   TEXT           NULLABLE
english_text    TEXT           NULLABLE
response_text   TEXT           NULLABLE
detected_lang   VARCHAR(10)    NULLABLE
audio_s3_uri    VARCHAR        NULLABLE
has_audio_out   BOOLEAN        DEFAULT FALSE
created_at      DATETIME       AUTO DEFAULT
```

**Constraints:**
- CHECK: role IN ('user', 'assistant')
- CHECK: content_type IN ('text', 'voice')

**Purpose:** Store chat messages with multilingual support

---

### 5. ALEMBIC_VERSION Table (1 column)
```
version_num     VARCHAR(32)    PRIMARY KEY, NOT NULL
```

**Purpose:** Track database migration version

---

## Indexes

All created as per migration:
- `ix_users_email` - UNIQUE index on users.email
- `ix_refresh_tokens_user_id` - Index on refresh_tokens.user_id
- `ix_messages_session_id` - Index on messages.session_id

---

## Foreign Keys

All with CASCADE DELETE:
1. `refresh_tokens.user_id` → `users.user_id`
2. `sessions.user_id` → `users.user_id`
3. `messages.session_id` → `sessions.session_id`

---

## Data Types Used

| Type | Purpose | Usage |
|------|---------|-------|
| VARCHAR(32) | UUID primary keys | user_id, session_id, message_id |
| VARCHAR(255) | Token JTI | jti (longer for token safety) |
| VARCHAR(10) | Enums | role, content_type, lang, detected_lang |
| VARCHAR | Variable strings | name, email, title, audio_s3_uri |
| TEXT | Large content | original_text, english_text, response_text |
| DATETIME | Timestamps | created_at, updated_at, expires_at |
| BOOLEAN | Flags | is_active, revoked, has_audio_out |

---

## Current State

**Database File:** bharatbot.db (SQLite)  
**Size:** ~56 KB (fresh, empty tables)  
**Tables:** 5 total  
**Rows:** 0 (ready for data)  
**Migration:** v1 Applied  
**Status:** ✅ READY FOR USE  

---

## How to Verify

```bash
# Using Python
python
>>> import sqlite3
>>> conn = sqlite3.connect('bharatbot.db')
>>> cursor = conn.cursor()
>>> cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
>>> [row[0] for row in cursor.fetchall()]
['alembic_version', 'users', 'refresh_tokens', 'sessions', 'messages']
```

---

## Ready to Use ✅

The database is **fully initialized** with:
- ✅ All tables created
- ✅ All columns present
- ✅ All constraints applied
- ✅ All indexes created
- ✅ All relationships defined

**Next:** Start the server and begin using the API!

---

**Verification Status:** PASSED ✅  
**Columns Missing:** NONE ✅  
**Tables Missing:** NONE ✅  
**Constraints Missing:** NONE ✅
