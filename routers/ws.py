"""
WebSocket routes — real-time two-way chat over a single persistent connection.

Protocol (JSON messages over WS):
──────────────────────────────────

CONNECTION:
  URL: /ws/chat?token=<JWT_access_token>
  or:  /ws/chat/<session_id>?token=<JWT_access_token>
  • Token must be a valid access token from /auth/login or /auth/signup
  • If token is invalid or missing, connection is rejected with close code 4401

CLIENT → SERVER:
  { "type": "text",  "text": "...",          "session_id": "..." }
  { "type": "voice", "audio_b64": "<base64>", "session_id": "..." }
  { "type": "ping" }

SERVER → CLIENT:
  { "type": "ack",      "mode": "text"|"voice" }        ← processing started
  { "type": "response", "data": {
                            "response_text": "...",
                            "audio_base64": "...",
                            "detected_langs": [...],
                            "dominant_lang": "...",
                            "transcript": "...",            ← only for voice
                            "english_input": "..." } }
  { "type": "error",    "error": { "code": "...", "message": "..." } }
  { "type": "pong" }

Notes:
  • One WebSocket connection can handle many turns — no reconnect needed.
  • Session history is loaded from DB before each pipeline call so the
    conversation context is always fresh.
  • Audio bytes arrive as base64 to keep the protocol pure JSON; the server
    decodes them before passing to the voice pipeline.
"""

import asyncio
import base64
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pipelines.bharatbot_pipeline import run_text_pipeline, run_voice_pipeline
from services.db import get_db, get_session_or_404, fetch_session_history, save_turn
from core.security import verify_ws_token

logger = logging.getLogger("BharatBot.ws")
router = APIRouter(tags=["websocket"])


async def _send(ws: WebSocket, payload: dict):
    """Helper — fire-and-forget JSON send with logging."""
    try:
        await ws.send_json(payload)
    except Exception as exc:
        logger.warning(f"[WS] send failed: {exc}")


def _log_timing(flow: str, session_id: str, phases: list[tuple[str, float]], t_total: float):
    """
    Emit a standardised timing summary block, identical in style to the
    HTTP pipeline logs.

    phases : list of (label, seconds) in chronological order
    """
    safe_total = max(t_total, 1e-9)
    logger.info(f"[{flow}] ════════════════════════════════════════════════════════")
    logger.info(f"[{flow}] END-TO-END TIMING SUMMARY (session={session_id})")
    logger.info(f"[{flow}] ────────────────────────────────────────────────────────")
    for label, secs in phases:
        logger.info(f"[{flow}]   {label:<28s} {secs:>6.2f}s ({100 * secs / safe_total:>5.1f}%)")
    logger.info(f"[{flow}] ────────────────────────────────────────────────────────")
    logger.info(f"[{flow}]   {'TOTAL':<28s} {t_total:>6.2f}s (100.0%)")
    logger.info(f"[{flow}] ════════════════════════════════════════════════════════")


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """
    Generic WebSocket chat endpoint.
    The client must pass session_id in every message and token in query param.
    
    URL: /ws/chat?token=<JWT_access_token>
    """
    # ── Extract and validate token from query params ──────────────────────
    token = websocket.query_params.get("token")
    try:
        user_id = await verify_ws_token(token)
    except Exception as exc:
        logger.warning(f"[WS] Token validation failed: {exc}")
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"[WS] connection accepted for user={user_id}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")

            # ── Ping/pong keepalive ────────────────────────────────────────
            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            session_id = data.get("session_id", "")

            # Load session language + history from DB (with ownership check)
            t_db_load_start = time.perf_counter()
            sess_lang = "en"
            history = []
            if session_id:
                try:
                    with get_db() as conn:
                        row = conn.execute(
                            "SELECT lang, user_id FROM sessions WHERE session_id = ? AND is_active = 1",
                            (session_id,),
                        ).fetchone()
                        if not row:
                            await _send(websocket, {
                                "type": "error",
                                "error": {"code": "SESSION_NOT_FOUND", "message": "Session not found."}
                            })
                            continue
                        if row["user_id"] != user_id:
                            await _send(websocket, {
                                "type": "error",
                                "error": {"code": "FORBIDDEN", "message": "You don't have access to this session."}
                            })
                            continue
                        sess_lang = row["lang"] or "en"
                        history = fetch_session_history(conn, session_id)
                except Exception as exc:
                    logger.warning(f"[WS] DB load failed: {exc}")
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "DB_ERROR", "message": "Database error occurred."}
                    })
                    continue
            t_db_load = time.perf_counter() - t_db_load_start

            # ── Text turn ─────────────────────────────────────────────────
            if msg_type == "text":
                text = data.get("text", "").strip()
                if not text:
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "EMPTY_TEXT", "message": "Empty text."}
                    })
                    continue

                await _send(websocket, {"type": "ack", "mode": "text"})

                t_total_start = time.perf_counter()
                try:
                    t_pipeline_start = time.perf_counter()
                    ctx = await run_text_pipeline(text, history, session_lang=sess_lang)
                    t_pipeline = time.perf_counter() - t_pipeline_start

                    audio_b64 = base64.b64encode(ctx.audio_bytes).decode() if ctx.audio_bytes else ""

                    t_db_save_start = time.perf_counter()
                    if session_id:
                        with get_db() as conn:
                            save_turn(
                                conn,
                                session_id=session_id,
                                content_type="text",
                                original_text=ctx.original_text,
                                english_text=ctx.english_text,
                                response_text=ctx.response_text,
                                detected_lang=ctx.dominant_lang,
                                has_audio_out=1 if audio_b64 else 0,
                            )
                    t_db_save = time.perf_counter() - t_db_save_start

                    t_total = time.perf_counter() - t_total_start

                    logger.info(
                        f"[TEXT FLOW] ⏱ Pipeline: {t_pipeline:.2f}s | "
                        f"input='{text[:60]}' dominant='{ctx.dominant_lang}'"
                    )
                    _log_timing("TEXT FLOW", session_id or "stateless", [
                        ("db_load",   t_db_load),
                        ("pipeline",  t_pipeline),
                        ("db_save",   t_db_save),
                    ], t_total + t_db_load)

                    await _send(websocket, {
                        "type":           "response",
                        "data": {
                            "response_text":  ctx.response_text,
                            "audio_base64":   audio_b64,
                            "detected_langs": ctx.detected_langs,
                            "dominant_lang":  ctx.dominant_lang,
                            "english_input":  ctx.english_text,
                        }
                    })

                except Exception as exc:
                    logger.exception("[WS] text pipeline error")
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "PIPELINE_ERROR", "message": str(exc)}
                    })

            # ── Voice turn ────────────────────────────────────────────────
            elif msg_type == "voice":
                audio_b64_in = data.get("audio_b64", "")
                if not audio_b64_in:
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "NO_AUDIO_DATA", "message": "No audio data."}
                    })
                    continue

                await _send(websocket, {"type": "ack", "mode": "voice"})

                t_total_start = time.perf_counter()
                try:
                    t_audio_read_start = time.perf_counter()
                    audio_bytes_in = base64.b64decode(audio_b64_in)
                    t_audio_read = time.perf_counter() - t_audio_read_start

                    t_pipeline_start = time.perf_counter()
                    ctx = await run_voice_pipeline(audio_bytes_in, history, session_lang=sess_lang)
                    t_pipeline = time.perf_counter() - t_pipeline_start

                    audio_b64_out = base64.b64encode(ctx.audio_bytes).decode() if ctx.audio_bytes else ""

                    t_db_save_start = time.perf_counter()
                    if session_id:
                        with get_db() as conn:
                            save_turn(
                                conn,
                                session_id=session_id,
                                content_type="voice",
                                original_text=ctx.original_text,
                                english_text=ctx.english_text,
                                response_text=ctx.response_text,
                                detected_lang=ctx.dominant_lang,
                                has_audio_out=1 if audio_b64_out else 0,
                            )
                    t_db_save = time.perf_counter() - t_db_save_start

                    t_total = time.perf_counter() - t_total_start

                    logger.info(
                        f"[VOICE FLOW] ⏱ Pipeline: {t_pipeline:.2f}s | "
                        f"transcript='{ctx.original_text[:60]}' dominant='{ctx.dominant_lang}'"
                    )
                    _log_timing("VOICE FLOW", session_id or "stateless", [
                        ("audio_read", t_audio_read),
                        ("db_load",    t_db_load),
                        ("pipeline",   t_pipeline),
                        ("db_save",    t_db_save),
                    ], t_total + t_db_load)

                    await _send(websocket, {
                        "type":           "response",
                        "data": {
                            "transcript":     ctx.original_text,
                            "response_text":  ctx.response_text,
                            "audio_base64":   audio_b64_out,
                            "detected_langs": ctx.detected_langs,
                            "dominant_lang":  ctx.dominant_lang,
                            "english_input":  ctx.english_text,
                        }
                    })

                except Exception as exc:
                    logger.exception("[WS] voice pipeline error")
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "PIPELINE_ERROR", "message": str(exc)}
                    })

            else:
                await _send(websocket, {
                    "type": "error",
                    "error": {"code": "UNKNOWN_TYPE", "message": f"Unknown type: {msg_type!r}"}
                })

    except WebSocketDisconnect:
        logger.info(f"[WS] client disconnected (user={user_id})")
    except Exception as exc:
        logger.exception(f"[WS] unexpected error (user={user_id}): {exc}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.websocket("/ws/chat/{session_id}")
async def ws_chat_session(websocket: WebSocket, session_id: str):
    """
    Session-scoped WebSocket — session_id comes from the URL path,
    so the client doesn't have to repeat it in every message.
    
    URL: /ws/chat/<session_id>?token=<JWT_access_token>
    """
    # ── Extract and validate token from query params ──────────────────────
    token = websocket.query_params.get("token")
    try:
        user_id = await verify_ws_token(token)
    except Exception as exc:
        logger.warning(f"[WS] Token validation failed: {exc}")
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"[WS] session connection accepted: {session_id!r} user={user_id}")

    # Load session language once at connection time (with ownership check)
    sess_lang = "en"
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT lang, user_id FROM sessions WHERE session_id = ? AND is_active = 1",
                (session_id,),
            ).fetchone()
            if not row:
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": "SESSION_NOT_FOUND", "message": "Session not found."}
                })
                await websocket.close(code=4404)
                return
            if row["user_id"] != user_id:
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": "FORBIDDEN", "message": "You don't have access to this session."}
                })
                await websocket.close(code=4403)
                return
            sess_lang = row["lang"] or "en"
    except Exception as exc:
        logger.error(f"[WS] DB error at connect: {exc}")
        await websocket.close(code=1011)
        return

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")

            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            # Reload history fresh every turn
            t_db_load_start = time.perf_counter()
            history = []
            try:
                with get_db() as conn:
                    history = fetch_session_history(conn, session_id)
            except Exception as exc:
                logger.warning(f"[WS] history load failed: {exc}")
            t_db_load = time.perf_counter() - t_db_load_start

            # ── Text turn ─────────────────────────────────────────────────
            if msg_type == "text":
                text = data.get("text", "").strip()
                if not text:
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "EMPTY_TEXT", "message": "Empty text."}
                    })
                    continue

                await _send(websocket, {"type": "ack", "mode": "text"})

                t_total_start = time.perf_counter()
                try:
                    t_pipeline_start = time.perf_counter()
                    ctx = await run_text_pipeline(text, history, session_lang=sess_lang)
                    t_pipeline = time.perf_counter() - t_pipeline_start

                    audio_b64 = base64.b64encode(ctx.audio_bytes).decode() if ctx.audio_bytes else ""

                    t_db_save_start = time.perf_counter()
                    with get_db() as conn:
                        save_turn(
                            conn,
                            session_id=session_id,
                            content_type="text",
                            original_text=ctx.original_text,
                            english_text=ctx.english_text,
                            response_text=ctx.response_text,
                            detected_lang=ctx.dominant_lang,
                            has_audio_out=1 if audio_b64 else 0,
                        )
                    t_db_save = time.perf_counter() - t_db_save_start

                    t_total = time.perf_counter() - t_total_start

                    logger.info(
                        f"[TEXT FLOW] ⏱ Pipeline: {t_pipeline:.2f}s | "
                        f"input='{text[:60]}' dominant='{ctx.dominant_lang}'"
                    )
                    _log_timing("TEXT FLOW", session_id, [
                        ("db_load",   t_db_load),
                        ("pipeline",  t_pipeline),
                        ("db_save",   t_db_save),
                    ], t_total + t_db_load)

                    await _send(websocket, {
                        "type":           "response",
                        "data": {
                            "response_text":  ctx.response_text,
                            "audio_base64":   audio_b64,
                            "detected_langs": ctx.detected_langs,
                            "dominant_lang":  ctx.dominant_lang,
                            "english_input":  ctx.english_text,
                        }
                    })

                except Exception as exc:
                    logger.exception(f"[WS:{session_id}] text pipeline error")
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "PIPELINE_ERROR", "message": str(exc)}
                    })

            # ── Voice turn ────────────────────────────────────────────────
            elif msg_type == "voice":
                audio_b64_in = data.get("audio_b64", "")
                if not audio_b64_in:
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "NO_AUDIO_DATA", "message": "No audio data."}
                    })
                    continue

                await _send(websocket, {"type": "ack", "mode": "voice"})

                t_total_start = time.perf_counter()
                try:
                    t_audio_read_start = time.perf_counter()
                    audio_bytes_in = base64.b64decode(audio_b64_in)
                    t_audio_read = time.perf_counter() - t_audio_read_start

                    t_pipeline_start = time.perf_counter()
                    ctx = await run_voice_pipeline(audio_bytes_in, history, session_lang=sess_lang)
                    t_pipeline = time.perf_counter() - t_pipeline_start

                    audio_b64_out = base64.b64encode(ctx.audio_bytes).decode() if ctx.audio_bytes else ""

                    t_db_save_start = time.perf_counter()
                    with get_db() as conn:
                        save_turn(
                            conn,
                            session_id=session_id,
                            content_type="voice",
                            original_text=ctx.original_text,
                            english_text=ctx.english_text,
                            response_text=ctx.response_text,
                            detected_lang=ctx.dominant_lang,
                            has_audio_out=1 if audio_b64_out else 0,
                        )
                    t_db_save = time.perf_counter() - t_db_save_start

                    t_total = time.perf_counter() - t_total_start

                    logger.info(
                        f"[VOICE FLOW] ⏱ Pipeline: {t_pipeline:.2f}s | "
                        f"transcript='{ctx.original_text[:60]}' dominant='{ctx.dominant_lang}'"
                    )
                    _log_timing("VOICE FLOW", session_id, [
                        ("audio_read", t_audio_read),
                        ("db_load",    t_db_load),
                        ("pipeline",   t_pipeline),
                        ("db_save",    t_db_save),
                    ], t_total + t_db_load)

                    await _send(websocket, {
                        "type":           "response",
                        "data": {
                            "transcript":     ctx.original_text,
                            "response_text":  ctx.response_text,
                            "audio_base64":   audio_b64_out,
                            "detected_langs": ctx.detected_langs,
                            "dominant_lang":  ctx.dominant_lang,
                            "english_input":  ctx.english_text,
                        }
                    })

                except Exception as exc:
                    logger.exception(f"[WS:{session_id}] voice pipeline error")
                    await _send(websocket, {
                        "type": "error",
                        "error": {"code": "PIPELINE_ERROR", "message": str(exc)}
                    })

            else:
                await _send(websocket, {
                    "type": "error",
                    "error": {"code": "UNKNOWN_TYPE", "message": f"Unknown type: {msg_type!r}"}
                })

    except WebSocketDisconnect:
        logger.info(f"[WS] session {session_id!r} disconnected (user={user_id})")
    except Exception as exc:
        logger.exception(f"[WS:{session_id}] unexpected error (user={user_id}): {exc}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
