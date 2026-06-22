"""
BharatBot — Multilingual Voice Chat  (Pipecat edition)
======================================================
Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import os
from pathlib import Path

# Path ko absolute bana dete hain taaki koi confusion na rahe
BASE_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
LOGS_DIR = BASE_DIR / "logs"

# Forcefully folder create karna (agar nahi bana toh python error throw karega)
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"--- LOGS FOLDER CREATED SUCCESSFULLY AT: {LOGS_DIR.resolve()} ---")
except Exception as e:
    print(f"--- FOLDER CREATION FAILED: {e} ---")

import time
import logging
import logging.handlers

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from services.aws_clients import BEDROCK_MODEL_ID, AWS_REGION, BEDROCK_KB_ID
from services.aws_clients import bedrock_agent
from services.db import init_db
from routers.sessions import router as sessions_router
from routers.chat import router as chat_router
from routers.ws import router as ws_router
from routers.auth import router as auth_router
from core.responses import error_response

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE   = "%Y-%m-%d %H:%M:%S"

# API Call Log Format (simpler for API logs)
API_LOG_FORMAT = "%(asctime)s %(message)s"

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))

_file_handler = logging.handlers.RotatingFileHandler(
    filename    = LOGS_DIR / "bharatbot.log",
    maxBytes    = 5 * 1024 * 1024,   # 5 MB
    backupCount = 5,
    encoding    = "utf-8",
)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))

# API-only log file (clean, concise API logs)
_api_log_handler = logging.handlers.RotatingFileHandler(
    filename    = LOGS_DIR / "api_calls.log",
    maxBytes    = 10 * 1024 * 1024,  # 10 MB
    backupCount = 5,
    encoding    = "utf-8",
)
_api_log_handler.setFormatter(logging.Formatter(API_LOG_FORMAT, datefmt=LOG_DATE))

# Set root logger to WARNING to suppress debug spam
logging.basicConfig(
    level=logging.WARNING,  # Changed from DEBUG to WARNING
    handlers=[_console_handler, _file_handler],
    force=True
)

# Suppress verbose loggers that create too much noise
QUIET_LOGGERS = {
    "uvicorn": logging.WARNING,           # No more header logs
    "uvicorn.error": logging.WARNING,     # No more verbose WebSocket debug
    "uvicorn.access": logging.WARNING,    # No more access logs to console
    "watchfiles": logging.ERROR,          # No file change monitoring logs
    "watchfiles.main": logging.ERROR,     # Suppress reload detection spam
    "pipecat": logging.WARNING,           # Still log errors from Pipecat
    "pipecat.pipeline": logging.WARNING,
    "pipecat.utils": logging.WARNING,
}

for logger_name, level in QUIET_LOGGERS.items():
    _l = logging.getLogger(logger_name)
    _l.setLevel(level)
    _l.handlers = []  # Clear default handlers
    _l.propagate = False  # Don't propagate to root (avoids duplicate logs)

# Main BharatBot logger - show API calls only
logger = logging.getLogger("BharatBot")
logger.setLevel(logging.INFO)  # Only INFO and above (no DEBUG spam)
logger.addHandler(_console_handler)
logger.addHandler(_file_handler)
logger.addHandler(_api_log_handler)
logger.propagate = False

def setup_file_logger():
    """Initialize logging (called on startup)."""
    logger.info("=" * 80)
    logger.info("BharatBot API Server Started")
    logger.info("=" * 80)

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="BharatBot — Multilingual Voice Chat (Pipecat)", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    path, method = request.url.path, request.method
    
    try:
        response = await call_next(request)
        ms = (time.time() - start) * 1000
        status = response.status_code
        
        # Format: TIMESTAMP | METHOD PATH | STATUS | TIME
        status_emoji = "✅" if 200 <= status < 300 else "⚠️" if 400 <= status < 500 else "❌"
        logger.info(f"{status_emoji} {method:6} {path:40} | {status:3} | {ms:6.1f}ms")
        
        return response
    except Exception as exc:
        ms = (time.time() - start) * 1000
        logger.error(f"❌ {method:6} {path:40} | ERROR | {ms:6.1f}ms | {type(exc).__name__}")
        raise


@app.on_event("startup")
async def startup():
    logger.info("Starting BharatBot (Pipecat edition)...")
    setup_file_logger()

    if BEDROCK_KB_ID:
        logger.info(f"Testing Bedrock Knowledge Base: {BEDROCK_KB_ID}")
        try:
            bedrock_agent.retrieve(
                knowledgeBaseId=BEDROCK_KB_ID,
                retrievalQuery={"text": "connection_test"},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 1}},
            )
            logger.info("Bedrock KB connection OK")
        except Exception as exc:
            logger.error(f"Bedrock KB failed: {exc}")
            logger.warning("RAG queries may fail; continuing in direct-LLM mode.")
    else:
        logger.info("No BEDROCK_KB_ID — running in direct-LLM mode.")

    init_db()
    logger.info("BharatBot ready.")


# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(ws_router)


# ─── Global Exception Handlers ────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTPException with standard response envelope."""
    error_code = getattr(exc, 'detail', 'UNKNOWN_ERROR')
    # If detail is already a dict-like error, use it; otherwise create new one
    if isinstance(error_code, str):
        message = error_code
        code = 'HTTP_ERROR'
    else:
        message = str(error_code)
        code = 'HTTP_ERROR'
    
    return error_response(code, message, status_code=exc.status_code)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return standard error envelope."""
    logger.exception(f"Unhandled exception: {exc}")
    return error_response(
        "INTERNAL_SERVER_ERROR",
        "An unexpected error occurred. Please try again later.",
        status_code=500,
    )


# ─── Misc ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": BEDROCK_MODEL_ID,
        "region": AWS_REGION,
        "framework": "pipecat",
    }


@app.get("/ui", response_class=HTMLResponse)
async def ui():
    ui_path = BASE_DIR / "bharatbot_ui2.html"
    if not ui_path.exists():
        return "<h1>UI file not found — place bharatbot_ui2.html in the same directory as main.py.</h1>"
    return ui_path.read_text(encoding="utf-8")