"""
Chat routes — all LLM/TTS/STT logic is delegated to the Pipecat pipeline.
The routes are responsible only for:
  1. Validating input / loading session state from DB.
  2. Calling the appropriate pipeline entry-point.
  3. Persisting the turn to SQLite.
  4. Returning the JSON response identical to the original API contract.

Extra utility endpoints (used by the UI):
  POST /tts                                      — on-demand TTS synthesis
  GET  /sessions/{id}/messages/{msg_id}/audio    — retrieve stored or synthesise audio for a past message
"""

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


# ─── Session-scoped chat ─────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/chat/text")
async def session_chat_text(session_id: str, text: str = Form(...), user_id: str = Depends(get_current_user)):
    timings = {}
    t_total = time.time()
    try:
        with get_db() as conn:
            session   = get_session_or_404(conn, session_id, user_id=user_id)
            history   = fetch_session_history(conn, session_id)
            sess_lang = session["lang"]

        # ── Pipecat pipeline ─────────────────────────────────────────────────
        t0              = time.time()
        ctx             = await run_text_pipeline(text, history, session_lang=sess_lang)
        timings["pipeline"] = time.time() - t0
        logger.info(
            f"[TEXT FLOW] ⏱ Pipeline: {timings['pipeline']:.2f}s | "
            f"dominant={ctx.dominant_lang!r} response={ctx.response_text[:60]!r}"
        )
        # ────────────────────────────────────────────────────────────────────

        audio_b64 = base64.b64encode(ctx.audio_bytes).decode()

        # ── DB Save ──────────────────────────────────────────────────────────
        t0 = time.time()
        with get_db() as conn:
            save_turn(
                conn,
                session_id=session_id,
                content_type="text",
                original_text=ctx.original_text,
                english_text=ctx.english_text,
                response_text=ctx.response_text,
                detected_lang=ctx.dominant_lang,
                has_audio_out=1,
            )
        timings["db_save"] = time.time() - t0

        total = time.time() - t_total

        # ── Timing summary ────────────────────────────────────────────────────
        logger.info(f"[TEXT FLOW] ════════════════════════════════════════════════════════")
        logger.info(f"[TEXT FLOW] END-TO-END TIMING SUMMARY (session={session_id})")
        logger.info(f"[TEXT FLOW] ────────────────────────────────────────────────────────")
        for stage, t in timings.items():
            pct = (t / total * 100) if total > 0 else 0
            logger.info(f"[TEXT FLOW]   {stage:<25}  {t:6.2f}s ({pct:5.1f}%)")
        logger.info(f"[TEXT FLOW] ────────────────────────────────────────────────────────")
        logger.info(f"[TEXT FLOW]   {'TOTAL':<25}  {total:6.2f}s (100.0%)")
        logger.info(f"[TEXT FLOW] ════════════════════════════════════════════════════════")

        return success_response({
            "session_id":     session_id,
            "detected_langs": ctx.detected_langs,
            "dominant_lang":  ctx.dominant_lang,
            "english_input":  ctx.english_text,
            "response_text":  ctx.response_text,
            "audio_base64":   audio_b64,
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in /sessions/{session_id}/chat/text")
        return error_response("CHAT_ERROR", str(exc), status_code=500)


@router.post("/sessions/{session_id}/chat/voice")
async def session_chat_voice(session_id: str, audio: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    if not S3_BUCKET:
        return error_response("CONFIG_ERROR", "S3_BUCKET_NAME not configured.", status_code=503)

    timings = {}
    t_total = time.time()
    try:
        with get_db() as conn:
            session   = get_session_or_404(conn, session_id, user_id=user_id)
            history   = fetch_session_history(conn, session_id)
            sess_lang = session["lang"]

        t0          = time.time()
        audio_bytes = await audio.read()
        timings["audio_read"] = time.time() - t0
        logger.info(f"[VOICE FLOW] session={session_id} audio_bytes={len(audio_bytes)}")

        # ── Pipecat pipeline ─────────────────────────────────────────────────
        t0  = time.time()
        ctx = await run_voice_pipeline(audio_bytes, history, session_lang=sess_lang)
        timings["pipeline"] = time.time() - t0
        logger.info(
            f"[VOICE FLOW] ⏱ Pipeline: {timings['pipeline']:.2f}s | "
            f"transcript={ctx.original_text!r} dominant={ctx.dominant_lang!r}"
        )
        # ────────────────────────────────────────────────────────────────────

        audio_b64 = base64.b64encode(ctx.audio_bytes).decode()

        # ── DB Save ──────────────────────────────────────────────────────────
        t0 = time.time()
        with get_db() as conn:
            save_turn(
                conn,
                session_id=session_id,
                content_type="voice",
                original_text=ctx.original_text,
                english_text=ctx.english_text,
                response_text=ctx.response_text,
                detected_lang=ctx.dominant_lang,
                audio_s3_uri=ctx.audio_s3_uri,
                has_audio_out=1,
            )
        timings["db_save"] = time.time() - t0

        total = time.time() - t_total

        # ── Timing summary ────────────────────────────────────────────────────
        logger.info(f"[VOICE FLOW] ════════════════════════════════════════════════════════")
        logger.info(f"[VOICE FLOW] END-TO-END TIMING SUMMARY (session={session_id})")
        logger.info(f"[VOICE FLOW] ────────────────────────────────────────────────────────")
        for stage, t in timings.items():
            pct = (t / total * 100) if total > 0 else 0
            logger.info(f"[VOICE FLOW]   {stage:<25}  {t:6.2f}s ({pct:5.1f}%)")
        logger.info(f"[VOICE FLOW] ────────────────────────────────────────────────────────")
        logger.info(f"[VOICE FLOW]   {'TOTAL':<25}  {total:6.2f}s (100.0%)")
        logger.info(f"[VOICE FLOW] ════════════════════════════════════════════════════════")

        return success_response({
            "session_id":     session_id,
            "detected_langs": ctx.detected_langs,
            "dominant_lang":  ctx.dominant_lang,
            "transcript":     ctx.original_text,
            "english_input":  ctx.english_text,
            "response_text":  ctx.response_text,
            "audio_base64":   audio_b64,
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in /sessions/{session_id}/chat/voice")
        return error_response("CHAT_ERROR", str(exc), status_code=500)
    

# ─── Legacy stateless chat (still requires auth) ────────────────────────────────

@router.post("/chat/text")
async def chat_text(text: str = Form(...), user_id: str = Depends(get_current_user)):
    try:
        # ── Pipecat pipeline ─────────────────────────────────────────────────
        ctx = await run_text_pipeline(text, history=[])
        # ────────────────────────────────────────────────────────────────────

        audio_b64 = base64.b64encode(ctx.audio_bytes).decode()

        return success_response({
            "detected_langs": ctx.detected_langs,
            "dominant_lang":  ctx.dominant_lang,
            "english_input":  ctx.english_text,
            "response_text":  ctx.response_text,
            "audio_base64":   audio_b64,
        })
    except Exception as exc:
        logger.exception("Error in /chat/text")
        return error_response("CHAT_ERROR", str(exc), status_code=500)


@router.post("/chat/voice")
async def chat_voice(audio: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    if not S3_BUCKET:
        return error_response("CONFIG_ERROR", "S3_BUCKET_NAME not configured.", status_code=503)
    try:
        audio_bytes = await audio.read()

        # ── Pipecat pipeline ─────────────────────────────────────────────────
        ctx = await run_voice_pipeline(audio_bytes, history=[])
        # ────────────────────────────────────────────────────────────────────

        audio_b64 = base64.b64encode(ctx.audio_bytes).decode()

        return success_response({
            "detected_langs": ctx.detected_langs,
            "dominant_lang":  ctx.dominant_lang,
            "transcript":     ctx.original_text,
            "english_input":  ctx.english_text,
            "response_text":  ctx.response_text,
            "audio_base64":   audio_b64,
        })
    except Exception as exc:
        logger.exception("Error in /chat/voice")
        return error_response("CHAT_ERROR", str(exc), status_code=500)


# ─── On-demand TTS  (POST /tts) ───────────────────────────────────────────────
#
# Called by the UI's "Regenerate audio" fallback button when stored audio is
# unavailable.  Accepts { text, lang } and returns { audio_base64 }.

class TTSRequest(BaseModel):
    text: str
    lang: str = "en"


@router.post("/tts")
async def tts(body: TTSRequest, user_id: str = Depends(get_current_user)):
    """
    Synthesise arbitrary text to MP3 via Amazon Polly and return base64.
    Used by the UI to regenerate audio for history messages on demand.
    """
    if not body.text.strip():
        return error_response("INVALID_INPUT", "text must not be empty.", status_code=422)

    try:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None, synthesise_speech, body.text, body.lang
        )
        audio_b64 = base64.b64encode(audio_bytes).decode()
        logger.info(f"[TTS] synthesised {len(audio_bytes)} bytes for lang={body.lang!r}")
        return success_response({"audio_base64": audio_b64, "lang": body.lang})

    except Exception as exc:
        logger.exception("Error in /tts")
        return error_response("TTS_ERROR", str(exc), status_code=500)


# ─── Per-message audio retrieval  (GET /sessions/{id}/messages/{msg_id}/audio) ─
#
# Called by the UI's "Load audio" button on history bot-bubbles.
#
# Strategy (two-tier):
#   1. If the message has an audio_s3_uri stored, generate a presigned S3 URL
#      and return { audio_url }.  The browser streams directly from S3 — no
#      base64 bloat, no server bandwidth.
#   2. Otherwise synthesise the response_text via Polly on-demand and return
#      { audio_base64 } so the UI can still play it.

_PRESIGN_EXPIRY = 3600   # seconds the presigned URL is valid


@router.get("/sessions/{session_id}/messages/{message_id}/audio")
async def get_message_audio(session_id: str, message_id: str, user_id: str = Depends(get_current_user)):
    """
    Return audio for a past assistant message.

    Response (one of):
      { "audio_url":    "<presigned S3 URL>" }   — stored Polly MP3 in S3
      { "audio_base64": "<base64 MP3>"       }   — synthesised on-demand
    """
    try:
        with get_db() as conn:
            get_session_or_404(conn, session_id, user_id=user_id)           # 404 if session gone or not owned
            msg = get_assistant_message(conn, session_id, message_id)       # 404 if not found

        lang          = msg["detected_lang"] or "en"
        audio_s3_uri  = msg["audio_s3_uri"]
        response_text = msg["response_text"] or ""

        # ── Tier 1: presigned S3 URL ──────────────────────────────────────
        if audio_s3_uri:
            try:
                # uri format: s3://<bucket>/<key>
                without_prefix = audio_s3_uri.removeprefix("s3://")
                bucket, _, key = without_prefix.partition("/")
                loop = asyncio.get_event_loop()
                url  = await loop.run_in_executor(
                    None,
                    lambda: s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": bucket, "Key": key},
                        ExpiresIn=_PRESIGN_EXPIRY,
                    ),
                )
                logger.info(f"[AUDIO] presigned URL generated for message {message_id}")
                return success_response({"audio_url": url, "lang": lang})
            except Exception as exc:
                logger.warning(
                    f"[AUDIO] presign failed for {audio_s3_uri!r}, "
                    f"falling back to on-demand TTS: {exc}"
                )

        # ── Tier 2: on-demand Polly synthesis ─────────────────────────────
        if not response_text.strip():
            return error_response("NO_TEXT_AVAILABLE", "No text available to synthesise.", status_code=404)

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None, synthesise_speech, response_text, lang
        )
        audio_b64 = base64.b64encode(audio_bytes).decode()
        logger.info(
            f"[AUDIO] on-demand synthesis for message {message_id} "
            f"({len(audio_bytes)} bytes, lang={lang!r})"
        )
        return success_response({"audio_base64": audio_b64, "lang": lang})

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in /sessions/{session_id}/messages/{message_id}/audio")
        return error_response("AUDIO_ERROR", str(exc), status_code=500)
