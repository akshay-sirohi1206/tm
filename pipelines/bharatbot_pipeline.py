"""
BharatBot Pipecat Pipeline  (pipecat-ai 1.x)
---------------------------------------------
Pipecat 1.x API:
  - PipelineWorker  (replaces PipelineTask)
  - WorkerRunner    (replaces PipelineRunner)
  - add_workers() is async and must be awaited

Frames flow through a linear pipeline:

  BharatBotFrame
        ↓
  LanguageDetectionProcessor   – detect language, translate input → English
        ↓
  BedrockLLMProcessor          – call Bedrock (direct or KB RAG)
        ↓
  TranslationProcessor         – translate English response → dominant lang
        ↓
  PollySynthesisProcessor      – convert text → MP3 bytes
        ↓
  OutputCollectorSink          – collect the finished BharatBotContext

Each processor is a pipecat FrameProcessor subclass.
A single BharatBotContext dataclass rides on the frame as shared state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from pipecat.frames.frames import DataFrame, EndFrame, Frame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor

from services.audio import synthesise_speech, transcribe_audio, upload_audio_to_s3, transcribe_audio_bytes
from services.language import detect_languages, translate_from_english, translate_to_english_mixed
from services.llm import call_bedrock

logger = logging.getLogger("BharatBot.pipeline")


# ─── Shared context ──────────────────────────────────────────────────────────

@dataclass
class BharatBotContext:
    """Mutable context carried through the pipeline via BharatBotFrame."""
    original_text:  str = ""
    english_text:   str = ""
    response_text:  str = ""
    detected_langs: List[str] = field(default_factory=list)
    dominant_lang:  str = "en"
    audio_s3_uri:   Optional[str] = None
    audio_bytes:    Optional[bytes] = None
    history:        List[dict] = field(default_factory=list)
    session_lang:   str = "en"


# ─── Custom frame ─────────────────────────────────────────────────────────────

class BharatBotFrame(DataFrame):
    """A single frame that carries the BharatBotContext through the pipeline."""

    def __init__(self, context: BharatBotContext):
        super().__init__()
        self.context = context


# ─── Processors ───────────────────────────────────────────────────────────────

class LanguageDetectionProcessor(FrameProcessor):
    """Detect language(s) and translate the original text to English."""

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, BharatBotFrame):
            ctx = frame.context
            try:
                ctx.detected_langs = detect_languages(ctx.original_text)
                ctx.dominant_lang = (
                    ctx.session_lang
                    if ctx.session_lang != "en"
                    else ctx.detected_langs[0]
                )
                loop = asyncio.get_event_loop()
                ctx.english_text = await loop.run_in_executor(
                    None, translate_to_english_mixed, ctx.original_text
                )
                logger.info(
                    f"[Pipeline:LangDetect] detected={ctx.detected_langs} "
                    f"dominant={ctx.dominant_lang!r} english={ctx.english_text[:60]!r}"
                )
            except Exception as e:
                logger.error(f"[Pipeline:LangDetect] error: {e}", exc_info=True)
                ctx.english_text = ctx.original_text
                ctx.detected_langs = [ctx.session_lang]
                ctx.dominant_lang = ctx.session_lang

        await self.push_frame(frame, direction)


class BedrockLLMProcessor(FrameProcessor):
    """Call Bedrock (direct or KB RAG) with the English-translated input."""

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, BharatBotFrame):
            ctx = frame.context
            try:
                loop = asyncio.get_event_loop()
                ctx.response_text = await loop.run_in_executor(
                    None, call_bedrock, ctx.english_text, ctx.history
                )
                logger.info(f"[Pipeline:LLM] response={ctx.response_text[:80]!r}")
            except Exception as e:
                logger.error(f"[Pipeline:LLM] error calling Bedrock: {e}", exc_info=True)
                ctx.response_text = "I encountered an error processing your request. Please try again."

        await self.push_frame(frame, direction)


class TranslationProcessor(FrameProcessor):
    """Translate the English LLM response back to the dominant language."""

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, BharatBotFrame):
            ctx = frame.context
            try:
                loop = asyncio.get_event_loop()
                ctx.response_text = await loop.run_in_executor(
                    None, translate_from_english, ctx.response_text, ctx.dominant_lang
                )
                logger.info(
                    f"[Pipeline:Translate] {ctx.dominant_lang}={ctx.response_text[:80]!r}"
                )
            except Exception as e:
                logger.error(f"[Pipeline:Translate] error translating to {ctx.dominant_lang}: {e}", exc_info=True)

        await self.push_frame(frame, direction)


class PollySynthesisProcessor(FrameProcessor):
    """Convert the translated response text to MP3 bytes via Amazon Polly."""

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, BharatBotFrame):
            ctx = frame.context
            try:
                loop = asyncio.get_event_loop()
                ctx.audio_bytes = await loop.run_in_executor(
                    None, synthesise_speech, ctx.response_text, ctx.dominant_lang
                )
                logger.info(
                    f"[Pipeline:Polly] {len(ctx.audio_bytes)} bytes lang={ctx.dominant_lang!r}"
                )
            except Exception as e:
                logger.error(f"[Pipeline:Polly] error synthesizing speech: {e}", exc_info=True)
                ctx.audio_bytes = b""

        await self.push_frame(frame, direction)


class OutputCollectorSink(FrameProcessor):
    """Terminal sink — stores the finished BharatBotContext for the caller."""

    def __init__(self):
        super().__init__()
        self.result: Optional[BharatBotContext] = None

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, BharatBotFrame):
            self.result = frame.context

        await self.push_frame(frame, direction)


# ─── Internal pipeline runner ─────────────────────────────────────────────────

async def _run_pipeline(ctx: BharatBotContext) -> BharatBotContext:
    """
    Build and run a one-shot Pipecat pipeline for a single BharatBotContext.
    Uses the pipecat 1.x API: PipelineWorker + WorkerRunner.
    """
    sink = OutputCollectorSink()

    pipeline = Pipeline([
        LanguageDetectionProcessor(),
        BedrockLLMProcessor(),
        TranslationProcessor(),
        PollySynthesisProcessor(),
        sink,
    ])

    worker = PipelineWorker(pipeline, name="bharatbot-worker")
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)

    try:
        await runner.add_workers(worker)             # async in 1.x — must be awaited
        await worker.queue_frames([BharatBotFrame(ctx), EndFrame()])
        await runner.run()
    except Exception as e:
        logger.error(f"[Pipeline:Runner] error during pipeline execution: {e}", exc_info=True)
        raise RuntimeError(f"Pipeline execution failed: {e}") from e

    if sink.result is None:
        logger.error("[Pipeline:Runner] Pipeline finished without producing a result. Check logs above for processor errors.")
        raise RuntimeError(
            "Pipeline finished without producing a result. "
            "This typically indicates a processor failed silently. "
            "Check application logs for detailed error messages."
        )

    return sink.result


# ─── Public entry-points ──────────────────────────────────────────────────────

async def run_text_pipeline(
    text: str,
    history: List[dict],
    session_lang: str = "en",
) -> BharatBotContext:
    """Run the BharatBot pipeline for a text input."""
    ctx = BharatBotContext(
        original_text=text,
        history=history,
        session_lang=session_lang,
    )
    return await _run_pipeline(ctx)


# async def run_voice_pipeline(
#     audio_bytes: bytes,
#     history: List[dict],
#     session_lang: str = "en",
# ) -> BharatBotContext:
#     """
#     Run the BharatBot pipeline for a voice input.
#     Transcription (STT) happens before the pipeline because it is I/O-heavy
#     and its result seeds the BharatBotContext that feeds into the pipeline.
#     """
#     loop = asyncio.get_event_loop()

#     s3_uri = await loop.run_in_executor(
#         None, upload_audio_to_s3, audio_bytes, ".webm"
#     )
#     transcript, transcribed_lang = await loop.run_in_executor(
#         None, transcribe_audio, s3_uri
#     )
#     logger.info(f"[Pipeline:Voice] transcript={transcript[:60]!r} lang={transcribed_lang!r}")

#     ctx = BharatBotContext(
#         original_text=transcript,
#         audio_s3_uri=s3_uri,
#         history=history,
#         session_lang=session_lang,
#     )
#     # Seed dominant_lang from Transcribe result so LanguageDetectionProcessor
#     # can refine it further if needed.
#     ctx.dominant_lang = (
#         transcribed_lang if transcribed_lang != "en"
#         else (session_lang if session_lang != "en" else "en")
#     )

#     result = await _run_pipeline(ctx)
#     result.audio_s3_uri = s3_uri   # preserve the input audio S3 URI
#     return result


async def run_voice_pipeline(
    audio_bytes: bytes,
    history: List[dict],
    session_lang: str = "en",
) -> BharatBotContext:
    """
    Run the BharatBot pipeline for a voice input.
    Transcription (STT) happens directly from audio bytes — no S3 upload needed.
    """
    loop = asyncio.get_event_loop()

    transcript, transcribed_lang = await loop.run_in_executor(
        None, transcribe_audio_bytes, audio_bytes
    )
    logger.info(f"[Pipeline:Voice] transcript={transcript[:60]!r} lang={transcribed_lang!r}")

    ctx = BharatBotContext(
        original_text=transcript,
        history=history,
        session_lang=session_lang,
    )
    ctx.dominant_lang = (
        transcribed_lang if transcribed_lang != "en"
        else (session_lang if session_lang != "en" else "en")
    )

    return await _run_pipeline(ctx)