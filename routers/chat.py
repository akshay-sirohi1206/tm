import asyncio
import base64
import logging
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipelines.bharatbot_pipeline import run_text_pipeline, run_voice_pipeline
from services.audio import synthesise_speech
from services.aws_clients import S3_BUCKET, S3_PREFIX, s3
from services.db import get_db, get_session_or_404, fetch_session_history, save_turn, get_assistant_message
from core.security import get_current_user
from core.responses import success_response, error_response

logger = logging.getLogger("BharatBot.chat")
router = APIRouter(tags=["chat"])


@router.post("/sessions/{session_id}/chat/text")
async def session_chat_text(session_id: str, text: str = Form(...), user_id: str = Depends(get_current_user)):
    """Submit plain text messages safely processed into RDS relational records."""
    t_start = time.perf_counter()
    if not text.strip():
        return error_response("EMPTY_TEXT", "Text body content cannot be empty.", status_code=400)

    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        history = fetch_session_history(conn, session_id, limit=12)

    logger.info(f"[CHAT] text pipeline running for session {session_id!r}...")
    try:
        pipeline_res = await run_text_pipeline(text, history)
        
        with get_db() as conn:
            save_turn(
                conn=conn,
                session_id=session_id,
                content_type="text",
                original_text=text,
                english_text=pipeline_res.english_text,
                response_text=pipeline_res.response_text,
                detected_lang=pipeline_res.dominant_lang,
                has_audio_out=0
            )

        t_total = time.perf_counter() - t_start
        logger.info(f"[CHAT] text turn finished processing successfully in {t_total:.2f}s")
        return success_response({
            "response_text":  pipeline_res.response_text,
            "detected_langs": pipeline_res.detected_langs,
            "dominant_lang":  pipeline_res.dominant_lang,
            "english_input":  pipeline_res.english_text,
        })

    except Exception as exc:
        logger.exception(f"Text pipeline processing failure: {exc}")
        return error_response("PIPELINE_ERROR", str(exc), status_code=500)


@router.post("/sessions/{session_id}/chat/voice")
async def session_chat_voice(
    session_id: str,
    audio: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    """Handle raw audio uploads streaming into S3 and recording into MySQL structural records."""
    t_start = time.perf_counter()
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        history = fetch_session_history(conn, session_id, limit=12)

    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            return error_response("EMPTY_AUDIO", "Uploaded audio bytes payload is missing.", status_code=400)

        # ── S3 Permanent Storage Mapping ──────────────────────────────
        file_uuid = uuid.uuid4().hex
        s3_key = f"{S3_PREFIX.strip('/')}/{session_id}/{file_uuid}.wav" if S3_PREFIX else f"audio/{session_id}/{file_uuid}.wav"
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: s3.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=audio_bytes,
                ContentType="audio/wav"
            )
        )
        s3_uri = f"s3://{S3_BUCKET}/{s3_key}"
        logger.info(f"[AUDIO] Persisted incoming audio turn to: {s3_uri}")

        # Pipeline invocation
        pipeline_res = await run_voice_pipeline(audio_bytes, history)
        
        audio_b64_out = None
        has_audio_out = 0
        if pipeline_res.response_audio:
            audio_b64_out = base64.b64encode(pipeline_res.response_audio).decode()
            has_audio_out = 1

        with get_db() as conn:
            save_turn(
                conn=conn,
                session_id=session_id,
                content_type="voice",
                original_text=pipeline_res.original_text or "",
                english_text=pipeline_res.english_text or "",
                response_text=pipeline_res.response_text,
                detected_lang=pipeline_res.dominant_lang,
                audio_s3_uri=s3_uri,
                has_audio_out=has_audio_out
            )

        t_total = time.perf_counter() - t_start
        logger.info(f"[CHAT] voice segment turn finalized successfully in {t_total:.2f}s")
        return success_response({
            "transcript":     pipeline_res.original_text,
            "response_text":  pipeline_res.response_text,
            "audio_base64":   audio_b64_out,
            "detected_langs": pipeline_res.detected_langs,
            "dominant_lang":  pipeline_res.dominant_lang,
            "english_input":  pipeline_res.english_text,
        })

    except Exception as exc:
        logger.exception(f"Voice compilation process pipeline failure: {exc}")
        return error_response("AUDIO_PIPELINE_ERROR", str(exc), status_code=500)


@router.get("/sessions/{session_id}/messages/{message_id}/audio")
async def get_message_audio(session_id: str, message_id: str, user_id: str = Depends(get_current_user)):
    """Fetch base64 voice recordings maps or synthesize on demand cleanly."""
    _PRESIGN_EXPIRY = 3600
    with get_db() as conn:
        get_session_or_404(conn, session_id, user_id=user_id)
        msg = get_assistant_message(conn, session_id, message_id)

    response_text = msg.get("response_text") or ""
    lang = msg.get("detected_lang") or "en"
    audio_s3_uri = msg.get("audio_s3_uri")

    try:
        if audio_s3_uri and audio_s3_uri.startswith("s3://"):
            try:
                parts = audio_s3_uri.replace("s3://", "").split("/", 1)
                bucket = parts[0]
                key = parts[1]
                url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=_PRESIGN_EXPIRY,
                )
                logger.info(f"[AUDIO] Pre-signed S3 download handle shared for: {message_id}")
                return success_response({"audio_url": url, "lang": lang})
            except Exception as exc:
                logger.warning(f"Fallback tracing on S3 integration endpoint triggered: {exc}")

        if not response_text.strip():
            return error_response("NO_TEXT_AVAILABLE", "No structural text track found to process sound metadata.", status_code=404)

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, synthesise_speech, response_text, lang)
        audio_b64 = base64.b64encode(audio_bytes).decode()
        return success_response({"audio_base64": audio_b64, "lang": lang})

    except Exception as exc:
        logger.exception(f"Media extraction layer unexpected failure context: {exc}")
        return error_response("AUDIO_STREAM_ERROR", str(exc), status_code=500)
    