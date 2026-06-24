"""
WebSocket routes — real-time two-way structural active pipelines inside AWS RDS instances.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from core.security import verify_access_token
from core.responses import success_response, error_response
from services.db import get_db, get_session_or_404, fetch_session_history, save_turn
from pipelines.bharatbot_pipeline import run_text_pipeline, run_voice_pipeline

logger = logging.getLogger("BharatBot.ws")
router = APIRouter(tags=["websocket"])


async def _send(ws: WebSocket, obj: dict):
    """Safely propagate outbound data frame streams."""
    try:
        await ws.send_text(json.dumps(obj))
    except Exception as e:
        logger.warning(f"Failed to transmit frame inside connection context pipeline: {e}")


@router.websocket("/ws/chat")
@router.websocket("/ws/chat/{session_id}")
async def websocket_chat_endpoint(websocket: WebSocket, session_id: Optional[str] = None):
    """Manage dynamic asynchronous multi-turn streaming pipelines via PyMySQL connection mappings."""
    await websocket.accept()
    
    token = websocket.query_params.get("token")
    if not token:
        logger.warning("[WS] Missing token context params rejection framework.")
        await websocket.close(code=4401)
        return

    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4401)
            return
    except Exception as exc:
        logger.warning(f"[WS] Token authentication processing rejection failure trace: {exc}")
        await websocket.close(code=4401)
        return

    logger.info(f"[WS] User connection authorized safely on thread user={user_id}. Listening active events.")

    try:
        while True:
            raw_data = await websocket.receive_text()
            t_start = time.perf_counter()
            
            try:
                data = json.loads(raw_data)
            except Exception:
                await _send(websocket, {"type": "error", "error": {"code": "BAD_JSON", "message": "Invalid JSON frame structural map"}})
                continue

            msg_type = data.get("type")
            target_session = data.get("session_id") or session_id

            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            if not target_session:
                await _send(websocket, {"type": "error", "error": {"code": "MISSING_SESSION", "message": "No active session reference identifier set"}})
                continue

            # ── Process Text Turns ──────────────────────────────────────────
            if msg_type == "text":
                text_content = data.get("text") or ""
                if not text_content.strip():
                    await _send(websocket, {"type": "error", "error": {"code": "EMPTY_TEXT", "message": "Empty message inputs shared"}})
                    continue

                await _send(websocket, {"type": "ack", "mode": "text"})

                with get_db() as conn:
                    get_session_or_404(conn, target_session, user_id=user_id)
                    history = fetch_session_history(conn, target_session, limit=12)

                try:
                    ctx = await run_text_pipeline(text_content, history)
                    
                    with get_db() as conn:
                        save_turn(
                            conn=conn,
                            session_id=target_session,
                            content_type="text",
                            original_text=text_content,
                            english_text=ctx.english_text,
                            response_text=ctx.response_text,
                            detected_lang=ctx.dominant_lang,
                            has_audio_out=0
                        )

                    await _send(websocket, {
                        "type": "response",
                        "data": {
                            "response_text":  ctx.response_text,
                            "detected_langs": ctx.detected_langs,
                            "dominant_lang":  ctx.dominant_lang,
                            "english_input":  ctx.english_text,
                        }
                    })
                except Exception as exc:
                    logger.exception(f"[WS:{target_session}] Text segment frame pipeline process failure")
                    await _send(websocket, {"type": "error", "error": {"code": "PIPELINE_ERROR", "message": str(exc)}})

            # ── Process Voice Turns ─────────────────────────────────────────
            elif msg_type == "voice":
                audio_b64_in = data.get("audio_b64") or ""
                if not audio_b64_in:
                    await _send(websocket, {"type": "error", "error": {"code": "EMPTY_AUDIO", "message": "Base64 payload array stream is empty"}})
                    continue

                await _send(websocket, {"type": "ack", "mode": "voice"})

                try:
                    audio_bytes = base64.b64decode(audio_b64_in)
                except Exception:
                    await _send(websocket, {"type": "error", "error": {"code": "INVALID_B64", "message": "Failed decoding base64 audio block stream"}})
                    continue

                with get_db() as conn:
                    get_session_or_404(conn, target_session, user_id=user_id)
                    history = fetch_session_history(conn, target_session, limit=12)

                try:
                    ctx = await run_voice_pipeline(audio_bytes, history)
                    
                    audio_b64_out = None
                    has_audio_out = 0
                    if ctx.response_audio:
                        audio_b64_out = base64.b64encode(ctx.response_audio).decode()
                        has_audio_out = 1

                    with get_db() as conn:
                        save_turn(
                            conn=conn,
                            session_id=target_session,
                            content_type="voice",
                            original_text=ctx.original_text or "",
                            english_text=ctx.english_text or "",
                            response_text=ctx.response_text,
                            detected_lang=ctx.dominant_lang,
                            has_audio_out=has_audio_out
                        )

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
                    logger.exception(f"[WS:{target_session}] Voice event block framework process pipeline error")
                    await _send(websocket, {"type": "error", "error": {"code": "PIPELINE_ERROR", "message": str(exc)}})

            else:
                await _send(websocket, {"type": "error", "error": {"code": "UNKNOWN_TYPE", "message": f"Unknown structural state type shared: {msg_type!r}"}})

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected voluntarily for user session code trace {session_id!r} (user={user_id})")
    except Exception as exc:
        logger.exception(f"[WS:{session_id}] Unexpected pipeline crash event handled safely for user user={user_id}: {exc}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        