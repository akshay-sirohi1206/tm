"""
Audio services: S3 upload, AWS Transcribe STT, Amazon Polly TTS.

Marathi / Polly note
--------------------
Polly has no native Marathi voice. Kajal (hi-IN, neural) reads Devanagari
script correctly for both Hindi and Marathi, so we map 'mr' → hi-IN.
Passing 'mr-IN' as LanguageCode raises an exception on the neural engine.
"""

import re
import uuid
import time
import json
import logging
from typing import Tuple

from services.aws_clients import s3, transcribe, polly, S3_BUCKET, S3_PREFIX, AWS_REGION
from services.language import _comprehend_detect_devanagari_lang


logger = logging.getLogger("BharatBot.audio")

_DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')

POLLY_VOICES = {
    "en": ("Joanna", "neural", "en-US"),
    "hi": ("Kajal",  "neural", "hi-IN"),
    "mr": ("Kajal",  "neural", "hi-IN"),   # Polly has no Marathi engine; Kajal reads Devanagari
}


# ─── S3 ──────────────────────────────────────────────────────────────────────

def upload_audio_to_s3(audio_bytes: bytes, suffix: str = ".webm") -> str:
    key = f"{S3_PREFIX}/{uuid.uuid4()}{suffix}"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=audio_bytes)
    return f"s3://{S3_BUCKET}/{key}"


# ─── Polly TTS ───────────────────────────────────────────────────────────────

def synthesise_speech(text: str, lang: str) -> bytes:
    """Convert text to MP3 bytes using Amazon Polly."""
    voice_id, engine, language_code = POLLY_VOICES.get(lang, ("Joanna", "neural", "en-US"))
    logger.info(
        f"[TTS] Polly lang={lang!r} → voice={voice_id!r} engine={engine!r} "
        f"language_code={language_code!r}"
    )
    resp = polly.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId=voice_id,
        Engine=engine,
        LanguageCode=language_code,
    )
    return resp["AudioStream"].read()


# ─── AWS Transcribe ──────────────────────────────────────────────────────────

def transcribe_audio(s3_uri: str) -> Tuple[str, str]:
    """
    Transcribe audio from S3 and return (transcript_text, language_code).

    Two-step language pipeline:
      1. AWS Transcribe with multi-language options → coarse en / hi label.
      2. If "hi" detected, re-verify via Comprehend to catch Marathi text
         (Transcribe does not return mr-IN in multi-language mode).
    """
    job_name = f"mlvc-{uuid.uuid4().hex[:12]}"
    logger.info(f"[TRANSCRIBE] Starting job: {job_name}")

    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": s3_uri},
        MediaFormat="webm",
        IdentifyMultipleLanguages=True,
        LanguageOptions=["en-IN", "hi-IN"], # mr-IN not supported in multi-lang mode
        OutputBucketName=S3_BUCKET,
        OutputKey=f"{S3_PREFIX}/{job_name}.json",
    )

    for _ in range(60):
        time.sleep(2)
        status = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        st = status["TranscriptionJob"]["TranscriptionJobStatus"]
        if st == "COMPLETED":
            logger.info(f"[TRANSCRIBE] Job {job_name} completed.")
            break
        if st == "FAILED":
            raise RuntimeError("Transcription job failed")

    obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{S3_PREFIX}/{job_name}.json")
    result = json.loads(obj["Body"].read())
    transcript = result["results"]["transcripts"][0]["transcript"]

    langs = status["TranscriptionJob"].get("LanguageCodes", [])
    raw = (
        max(langs, key=lambda x: x.get("DurationInSeconds", 0)).get("LanguageCode", "en-IN")
        if langs
        else status["TranscriptionJob"].get("LanguageCode", "en-IN")
    )

    lang_code = "hi" if raw.startswith("hi") else "en"

    # Comprehend reclassification: hi → mr if transcript is actually Marathi
    if lang_code == "hi" and _DEVANAGARI_RE.search(transcript):
        comprehend_lang = _comprehend_detect_devanagari_lang(transcript)
        if comprehend_lang == "mr":
            lang_code = "mr"
            logger.info("[TRANSCRIBE] Comprehend reclassified transcript: hi → mr")
        else:
            logger.info(f"[TRANSCRIBE] Comprehend confirmed lang={comprehend_lang!r}")

    logger.info(f"[TRANSCRIBE] Final lang_code={lang_code!r} transcript={transcript[:60]!r}")
    return transcript, lang_code


import asyncio
import amazon_transcribe.client as _tc
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
from amazon_transcribe.auth import StaticCredentialResolver

# ─── AWS Transcribe Streaming STT ────────────────────────────────────────────

def transcribe_audio_bytes(audio_bytes: bytes) -> Tuple[str, str]:
    """
    Transcribe audio directly from bytes using Amazon Transcribe Streaming.
    Returns (transcript_text, language_code) — same contract as transcribe_audio().

    Two-step language pipeline (same as batch version):
      1. Transcribe streaming with auto language detection (en-IN / hi-IN).
      2. Comprehend reclassification hi → mr if Devanagari text detected.
    """
    transcript, lang_code = asyncio.run(_transcribe_streaming(audio_bytes))

    # Comprehend reclassification: hi → mr if transcript is actually Marathi
    if lang_code == "hi" and _DEVANAGARI_RE.search(transcript):
        comprehend_lang = _comprehend_detect_devanagari_lang(transcript)
        if comprehend_lang == "mr":
            lang_code = "mr"
            logger.info("[TRANSCRIBE:STREAM] Comprehend reclassified: hi → mr")
        else:
            logger.info(f"[TRANSCRIBE:STREAM] Comprehend confirmed lang={comprehend_lang!r}")

    logger.info(f"[TRANSCRIBE:STREAM] lang={lang_code!r} transcript={transcript[:60]!r}")
    return transcript, lang_code


async def _transcribe_streaming(audio_bytes: bytes) -> Tuple[str, str]:
    """Internal async streaming transcription using amazon-transcribe SDK with boto3 credentials."""

    class _Handler(TranscriptResultStreamHandler):
        def __init__(self, stream):
            super().__init__(stream)
            self.parts: list[str] = []
            self.lang: str = "en"

        async def handle_transcript_event(self, event: TranscriptEvent):
            for result in event.transcript.results:
                if not result.is_partial:
                    alt = result.alternatives[0]
                    self.parts.append(alt.transcript)
                    if hasattr(result, "language_code") and result.language_code:
                        self.lang = result.language_code

    # ── boto3 se credentials ──────────────────────────────────────────────────
    import boto3
    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()

    client = _tc.TranscribeStreamingClient(
        region=AWS_REGION,
        credential_resolver=StaticCredentialResolver(
            access_key_id=creds.access_key,
            secret_access_key=creds.secret_key,
            session_token=creds.token,
        ),
    )

    stream = await client.start_stream_transcription(
        language_code=None,
        media_sample_rate_hz=16000,
        media_encoding="pcm",
        identify_language=True,
        language_options=["en-IN", "hi-IN"],
    )

    handler = _Handler(stream.output_stream)

    async def _send():
        chunk_size = 8192
        for i in range(0, len(audio_bytes), chunk_size):
            await stream.input_stream.send_audio_event(
                audio_chunk=audio_bytes[i : i + chunk_size]
            )
        await stream.input_stream.end_stream()

    await asyncio.gather(_send(), handler.handle_events())

    transcript = " ".join(handler.parts).strip()
    raw_lang   = handler.lang
    lang_code  = "hi" if raw_lang.startswith("hi") else "en"

    return transcript, lang_code
