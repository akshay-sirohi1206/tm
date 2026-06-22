"""
Language detection & translation utilities.

Detection pipeline
------------------
Script detection  →  Devanagari present? use Comprehend to pick hi vs mr.
                     Latin present?     tag "en".
Translation       →  Translate is used ONLY for text conversion (not detection).
"""

import re
import logging
from typing import List

from services.aws_clients import translate, comprehend

logger = logging.getLogger("BharatBot.language")

SUPPORTED_LANGS = {"en", "hi", "mr"}

_DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')
_LATIN_RE      = re.compile(r'[A-Za-z]')


# ─── Comprehend-based Devanagari language detection ──────────────────────────

def _comprehend_detect_devanagari_lang(text: str) -> str:
    """
    Use Amazon Comprehend to detect whether Devanagari text is Hindi ('hi')
    or Marathi ('mr'). Falls back to 'hi' on any error or low-confidence result.

    Comprehend is trained on word/token distributions per language, so it
    correctly distinguishes Hindi from Marathi—unlike Translate auto-detect,
    which was the original root cause of hi/mr confusion.
    """
    if not text.strip():
        return "hi"
    try:
        resp = comprehend.detect_dominant_language(Text=text[:500])
        languages = resp.get("Languages", [])
        logger.info(f"[COMPREHEND] raw detection: {languages}")

        for lang_obj in languages:
            code  = lang_obj.get("LanguageCode", "")
            score = lang_obj.get("Score", 0.0)
            if code in SUPPORTED_LANGS:
                logger.info(f"[COMPREHEND] selected lang={code!r} score={score:.3f}")
                return code
            if code == "ne":          # Nepali also uses Devanagari — treat as Hindi
                logger.info("[COMPREHEND] Nepali detected, treating as Hindi")
                return "hi"

        logger.warning("[COMPREHEND] No supported Devanagari lang found, defaulting to 'hi'")
        return "hi"

    except Exception as exc:
        logger.warning(f"[COMPREHEND] detect_dominant_language failed: {exc}")
        return "hi"


# ─── Public helpers ──────────────────────────────────────────────────────────

def detect_languages(text: str) -> List[str]:
    """
    Return a priority-ordered list of detected languages, e.g. ['hi', 'en'].
    The first element is the dominant language (used for TTS + response translation).
    """
    detected: List[str] = []

    if _DEVANAGARI_RE.search(text):
        detected.append(_comprehend_detect_devanagari_lang(text))
    if _LATIN_RE.search(text):
        detected.append("en")

    return detected or ["en"]


def _split_on_script(text: str) -> list:
    """Split text into (chunk, 'deva'|'latin') pairs on script boundaries."""
    chunks: list = []
    current_script = None
    current: list = []

    for ch in text:
        if '\u0900' <= ch <= '\u097F':
            s = 'deva'
        elif ch.isalpha():
            s = 'latin'
        else:
            s = current_script or 'latin'

        if s != current_script and current_script is not None:
            chunks.append((''.join(current), current_script))
            current = []
        current_script = s
        current.append(ch)

    if current:
        chunks.append((''.join(current), current_script or 'latin'))

    return chunks


def translate_to_english_mixed(text: str) -> str:
    """
    Translate code-switched (Devanagari + Latin) text to English.
    Devanagari chunks → AWS Translate.  Latin chunks → pass-through.
    Translate is used ONLY for TEXT CONVERSION here, not for language detection.
    """
    chunks = _split_on_script(text)
    result: list = []

    for chunk_text, script in chunks:
        stripped = chunk_text.strip()
        if not stripped:
            result.append(chunk_text)
            continue

        if script == 'latin':
            result.append(chunk_text)
        else:
            try:
                resp = translate.translate_text(
                    Text=stripped,
                    SourceLanguageCode="auto",
                    TargetLanguageCode="en",
                )
                result.append(' ' + resp["TranslatedText"] + ' ')
            except Exception as exc:
                logger.warning(f"Chunk translation failed for '{stripped[:30]}': {exc}")
                result.append(chunk_text)

    return ' '.join(' '.join(result).split())


def translate_from_english(text: str, target_lang: str) -> str:
    if target_lang == "en":
        return text
    resp = translate.translate_text(
        Text=text, SourceLanguageCode="en", TargetLanguageCode=target_lang
    )
    return resp["TranslatedText"]
