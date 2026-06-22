# BharatBot API Reference

## Overview

This document describes every endpoint in the BharatBot API v3.0.0. All endpoints use standard JSON request/response formats and support user authentication via JWT tokens.

### Authentication

Most endpoints require **Bearer token authentication** via the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Access tokens are obtained from `/auth/signup` or `/auth/login` and expire after a configurable period (default 15 minutes). Use the `refresh_token` to obtain a new access token via `/auth/refresh`.

### Response Envelope

All successful responses follow this format:

```json
{
  "success": true,
  "data": { /* endpoint-specific data */ },
  "error": null,
  "meta": {
    "timestamp": "2024-01-01T12:00:00Z"
  }
}
```

All error responses follow this format:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message"
  },
  "meta": {
    "timestamp": "2024-01-01T12:00:00Z"
  }
}
```

---

## Authentication Endpoints

### POST /auth/signup

**Description:** Register a new user and auto-login.

**Auth Required:** No

**Request Body:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "SecurePass123!"
}
```

**Password Policy:**
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character (!@#$%^&*(),.?":{}|<>)
- No leading/trailing whitespace
- Cannot be the same as email or name

**Success Response (201):**
```json
{
  "success": true,
  "data": {
    "user": {
      "user_id": "a1b2c3d4e5f6g7h8",
      "name": "John Doe",
      "email": "john@example.com"
    },
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "token_type": "bearer"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `409 CONFLICT` — Email already registered
- `422 UNPROCESSABLE_ENTITY` — Invalid password (see error message for which rules failed)

---

### POST /auth/login

**Description:** Authenticate user by email and password.

**Auth Required:** No

**Request Body:**
```json
{
  "email": "john@example.com",
  "password": "SecurePass123!"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "token_type": "bearer"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `401 UNAUTHORIZED` — Invalid email or password (generic error, doesn't leak whether email exists)

---

### POST /auth/refresh

**Description:** Exchange a refresh token for a new access token. Refresh token is rotated (old one revoked, new one issued).

**Auth Required:** No

**Request Body:**
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "token_type": "bearer"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `401 UNAUTHORIZED` — Token is invalid, expired, or revoked

---

### GET /auth/me

**Description:** Get authenticated user's profile.

**Auth Required:** Yes (Bearer token)

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "user_id": "a1b2c3d4e5f6g7h8",
    "name": "John Doe",
    "email": "john@example.com",
    "created_at": "2024-01-01T12:00:00Z",
    "is_active": true
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `401 UNAUTHORIZED` — Missing or invalid access token
- `404 NOT_FOUND` — User not found

---

### POST /auth/logout

**Description:** Revoke a refresh token (logout / "forget this device").

**Auth Required:** Yes (Bearer token)

**Request Body:**
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Logged out successfully."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `401 UNAUTHORIZED` — Invalid refresh token
- `403 FORBIDDEN` — Trying to revoke another user's token

---

### POST /auth/change-password

**Description:** Change user password. Requires current password, revokes all other sessions on success.

**Auth Required:** Yes (Bearer token)

**Request Body:**
```json
{
  "current_password": "SecurePass123!",
  "new_password": "NewSecurePass456!"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Password changed successfully. All other sessions have been logged out."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `401 UNAUTHORIZED` — Current password is incorrect
- `404 NOT_FOUND` — User not found
- `422 UNPROCESSABLE_ENTITY` — New password doesn't meet policy requirements

---

## Thread/Session Endpoints

All thread endpoints require authentication. Threads are user-scoped — you can only access threads you created.

### POST /sessions

**Description:** Create a new chat thread (session) for the authenticated user.

**Auth Required:** Yes

**Request Body:**
```json
{
  "title": "Project Brainstorm",
  "lang": "en"
}
```

**Success Response (201):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "title": "Project Brainstorm",
    "lang": "en"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

---

### GET /sessions

**Description:** List all threads for the authenticated user.

**Auth Required:** Yes

**Query Parameters:**
- `limit` (int, default 20): Number of threads per page
- `offset` (int, default 0): Pagination offset

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "sessions": [
      {
        "session_id": "sess_abc123",
        "title": "Project Brainstorm",
        "lang": "en",
        "created_at": "2024-01-01T12:00:00Z",
        "updated_at": "2024-01-02T14:30:00Z",
        "message_count": 5
      }
    ],
    "limit": 20,
    "offset": 0
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

---

### GET /sessions/{session_id}

**Description:** Get details of a specific thread (ownership verified).

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "user_id": "user_xyz",
    "title": "Project Brainstorm",
    "lang": "en",
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-01-02T14:30:00Z",
    "is_active": 1,
    "message_count": 5
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist

---

### PATCH /sessions/{session_id}

**Description:** Update thread metadata (title, language).

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Request Body:**
```json
{
  "title": "Updated Title",
  "lang": "hi"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "updated": true
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist

---

### DELETE /sessions/{session_id}

**Description:** Soft-delete a thread (marks as inactive, preserves history).

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Success Response (204):** No content

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist

---

### GET /sessions/{session_id}/messages

**Description:** Get all messages in a thread.

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Query Parameters:**
- `limit` (int, default 50): Messages per page
- `offset` (int, default 0): Pagination offset

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "total": 5,
    "limit": 50,
    "offset": 0,
    "messages": [
      {
        "message_id": "msg_1",
        "role": "user",
        "content_type": "text",
        "original_text": "What is AI?",
        "response_text": "AI stands for Artificial Intelligence...",
        "detected_lang": "en",
        "has_audio_out": 1,
        "created_at": "2024-01-01T12:00:00Z"
      }
    ]
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

---

### DELETE /sessions/{session_id}/messages

**Description:** Clear all messages in a thread (but keep the thread).

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Success Response (204):** No content

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist

---

## Chat Endpoints

### POST /sessions/{session_id}/chat/text

**Description:** Send text input to a thread and get a response.

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Request Body:** Form data
- `text` (string, required): Input text

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "english_input": "What is AI?",
    "response_text": "AI stands for Artificial Intelligence...",
    "audio_base64": "SUQzBAAAI1QU..."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist
- `500 INTERNAL_SERVER_ERROR` — Pipeline or LLM error

---

### POST /sessions/{session_id}/chat/voice

**Description:** Send audio input to a thread and get a response.

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID

**Request Body:** Multipart form data
- `audio` (file, required): Audio file (WAV, MP3, etc.)

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "transcript": "What is AI?",
    "english_input": "What is AI?",
    "response_text": "AI stands for Artificial Intelligence...",
    "audio_base64": "SUQzBAAAI1QU..."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread doesn't exist
- `503 SERVICE_UNAVAILABLE` — S3 not configured
- `500 INTERNAL_SERVER_ERROR` — Pipeline, STT, or LLM error

---

### POST /chat/text

**Description:** Stateless text chat (no session/history).

**Auth Required:** Yes

**Request Body:** Form data
- `text` (string, required): Input text

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "english_input": "What is AI?",
    "response_text": "AI stands for Artificial Intelligence...",
    "audio_base64": "SUQzBAAAI1QU..."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

---

### POST /chat/voice

**Description:** Stateless voice chat (no session/history).

**Auth Required:** Yes

**Request Body:** Multipart form data
- `audio` (file, required): Audio file

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "transcript": "What is AI?",
    "english_input": "What is AI?",
    "response_text": "AI stands for Artificial Intelligence...",
    "audio_base64": "SUQzBAAAI1QU..."
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

---

### POST /tts

**Description:** On-demand text-to-speech synthesis.

**Auth Required:** Yes

**Request Body:**
```json
{
  "text": "Hello world",
  "lang": "en"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "audio_base64": "SUQzBAAAI1QU...",
    "lang": "en"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `422 UNPROCESSABLE_ENTITY` — Empty text
- `500 INTERNAL_SERVER_ERROR` — TTS service error

---

### GET /sessions/{session_id}/messages/{message_id}/audio

**Description:** Retrieve audio for a past assistant message (presigned S3 URL if available, otherwise on-demand synthesis).

**Auth Required:** Yes

**Path Parameters:**
- `session_id` (string): Thread ID
- `message_id` (string): Message ID

**Success Response (200):**
```json
{
  "success": true,
  "data": {
    "audio_url": "https://s3.amazonaws.com/bucket/key?signature=...",
    "lang": "en"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

Or (fallback):
```json
{
  "success": true,
  "data": {
    "audio_base64": "SUQzBAAAI1QU...",
    "lang": "en"
  },
  "error": null,
  "meta": {"timestamp": "2024-01-01T12:00:00Z"}
}
```

**Error Responses:**
- `403 FORBIDDEN` — Thread belongs to another user
- `404 NOT_FOUND` — Thread or message doesn't exist; or no text available for synthesis

---

## WebSocket Endpoints

WebSocket connections require authentication via a query parameter token. The token must be a valid access token.

### WS /ws/chat

**Description:** Generic WebSocket chat endpoint. Client passes `session_id` in every message.

**URL:** `ws://localhost:8000/ws/chat?token=<access_token>`

**Client Messages:**

Text input:
```json
{
  "type": "text",
  "text": "What is AI?",
  "session_id": "sess_abc123"
}
```

Voice input:
```json
{
  "type": "voice",
  "audio_b64": "SUQzBAAAI1QU...",
  "session_id": "sess_abc123"
}
```

Keepalive:
```json
{
  "type": "ping"
}
```

**Server Messages:**

Acknowledgement:
```json
{
  "type": "ack",
  "mode": "text"
}
```

Response:
```json
{
  "type": "response",
  "data": {
    "response_text": "AI stands for...",
    "audio_base64": "SUQzBAAAI1QU...",
    "detected_langs": ["en"],
    "dominant_lang": "en",
    "english_input": "What is AI?"
  }
}
```

Error:
```json
{
  "type": "error",
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session not found."
  }
}
```

Keepalive:
```json
{
  "type": "pong"
}
```

**Close Codes:**
- `4401` — Unauthorized (invalid/missing token)
- `4403` — Forbidden (session doesn't belong to user)
- `4404` — Session not found
- `1011` — Internal server error

---

### WS /ws/chat/{session_id}

**Description:** Session-scoped WebSocket. Client doesn't repeat `session_id` in messages.

**URL:** `ws://localhost:8000/ws/chat/<session_id>?token=<access_token>`

**Client Messages:**

Text input:
```json
{
  "type": "text",
  "text": "What is AI?"
}
```

Voice input:
```json
{
  "type": "voice",
  "audio_b64": "SUQzBAAAI1QU..."
}
```

Keepalive:
```json
{
  "type": "ping"
}
```

**Server Messages:** Same as `/ws/chat`

---

## Error Codes Reference

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `INVALID_PASSWORD` | 422 | Password doesn't meet policy |
| `EMAIL_ALREADY_EXISTS` | 409 | Email already registered |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password |
| `INVALID_REFRESH_TOKEN` | 401 | Refresh token is invalid/expired/revoked |
| `INVALID_ACCESS_TOKEN` | 401 | Access token is invalid/expired |
| `USER_NOT_FOUND` | 404 | User doesn't exist |
| `SESSION_NOT_FOUND` | 404 | Thread doesn't exist |
| `FORBIDDEN` | 403 | Thread/resource belongs to another user |
| `EMPTY_TEXT` | 400 | Text input is empty |
| `NO_AUDIO_DATA` | 400 | Audio data is missing |
| `NO_TEXT_AVAILABLE` | 404 | No text to synthesize |
| `CONFIG_ERROR` | 503 | Service misconfigured (e.g., S3) |
| `CHAT_ERROR` | 500 | Pipeline/LLM error |
| `TTS_ERROR` | 500 | Text-to-speech synthesis failed |
| `AUDIO_ERROR` | 500 | Audio retrieval/synthesis failed |
| `DB_ERROR` | 500 | Database error |
| `PIPELINE_ERROR` | 500 | LLM pipeline error |
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected server error |

---

## Health Check

### GET /health

**Description:** System health check.

**Auth Required:** No

**Success Response (200):**
```json
{
  "status": "ok",
  "model": "amazon.nova-lite-v1:0",
  "region": "us-east-1",
  "framework": "pipecat",
  "version": "3.0.0"
}
```
