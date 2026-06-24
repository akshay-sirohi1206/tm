"""
BharatBot — Multilingual Voice Chat  (Pipecat edition)
======================================================
Run Local:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import os
import time
import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, status, APIRouter  # 👈 APIRouter add kiya
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
# 🚀 STEP 1: IMPORT MANGUM ADAPTER
from mangum import Mangum

from services.aws_clients import BEDROCK_MODEL_ID, AWS_REGION, BEDROCK_KB_ID
from services.aws_clients import bedrock_agent
from services.db import init_db
from routers.sessions import router as sessions_router
from routers.chat import router as chat_router
from routers.ws import router as ws_router
from routers.auth import router as auth_router
from core.responses import error_response

BASE_DIR = Path(os.path.abspath(os.path.dirname(__file__)))

# 🚀 STEP 2: DYNAMIC LOGGING FOR LAMBDA (ENVIRONMENT DETECTOR)
IS_LAMBDA = os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE   = "%Y-%m-%d %H:%M:%S"
API_LOG_FORMAT = "%(asctime)s %(message)s"

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))

# Base root initialization
handlers_list = [_console_handler]

if not IS_LAMBDA:
    LOGS_DIR = BASE_DIR / "logs"
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        _file_handler = logging.handlers.RotatingFileHandler(
            filename    = LOGS_DIR / "bharatbot.log",
            maxBytes    = 5 * 1024 * 1024,
            backupCount = 5,
            encoding    = "utf-8",
        )
        _file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))
        handlers_list.append(_file_handler)

        _api_log_handler = logging.handlers.RotatingFileHandler(
            filename    = LOGS_DIR / "api_calls.log",
            maxBytes    = 10 * 1024 * 1024,
            backupCount = 5,
            encoding    = "utf-8",
        )
        _api_log_handler.setFormatter(logging.Formatter(API_LOG_FORMAT, datefmt=LOG_DATE))
    except Exception as e:
        print(f"--- LOCAL FILE LOGGING ENGINE STORAGE BLOCK DIRECTORY SKIPPED: {e} ---")

logging.basicConfig(
    level=logging.WARNING,
    handlers=handlers_list,
    force=True
)

QUIET_LOGGERS = {
    "uvicorn": logging.WARNING,
    "uvicorn.error": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "watchfiles": logging.ERROR,
    "watchfiles.main": logging.ERROR,
    "pipecat": logging.WARNING,
    "pipecat.pipeline": logging.WARNING,
    "pipecat.utils": logging.WARNING,
}

for logger_name, level in QUIET_LOGGERS.items():
    _l = logging.getLogger(logger_name)
    _l.setLevel(level)
    _l.handlers = []
    _l.propagate = False

logger = logging.getLogger("BharatBot")
logger.setLevel(logging.INFO)
logger.addHandler(_console_handler)

if not IS_LAMBDA and '_file_handler' in locals():
    logger.addHandler(_file_handler)
    logger.addHandler(_api_log_handler)

logger.propagate = False

def setup_file_logger():
    logger.info("=" * 80)
    logger.info(f"BharatBot API Server Initialized Engine Mode: {'AWS_LAMBDA' if IS_LAMBDA else 'LOCAL_HOST'}")
    logger.info("=" * 80)

# ─── App Definition ──────────────────────────────────────────────────────────

# Swager docs ko hum /api/docs aur /api/openapi.json par override kar rahe hain taaki frontend se na takraye
app = FastAPI(
    title="BharatBot — Multilingual Voice Chat (Pipecat)", 
    version="3.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

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
        status_code = response.status_code
        status_emoji = "✅" if 200 <= status_code < 300 else "⚠️" if 400 <= status_code < 500 else "❌"
        logger.info(f"{status_emoji} {method:6} {path:40} | {status_code:3} | {ms:6.1f}ms")
        return response
    except Exception as exc:
        ms = (time.time() - start) * 1000
        logger.error(f"❌ {method:6} {path:40} | ERROR | {ms:6.1f}ms | {type(exc).__name__}")
        raise

@app.on_event("startup")
async def startup():
    logger.info("Starting BharatBot Core Initialization Steps...")
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
    else:
        logger.info("No BEDROCK_KB_ID found — bypassing vector sync mapping rules.")

    init_db()
    logger.info("BharatBot Server Ready for triggers.")

# ─── Routers With Path-Routing Prefix Wrapper ─────────────────────────────────
# ✨ UPDATED: Ek main master api_router banaya jo saare sub-routers ko /api deta hai
api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(sessions_router)
api_router.include_router(chat_router)
api_router.include_router(ws_router)

# ─── Verification Checkpoints (Inside Prefix) ─────────────────────────────────
@api_router.get("/health")
async def health():
    return {
        "status": "ok",
        "model": BEDROCK_MODEL_ID,
        "region": AWS_REGION,
        "framework": "pipecat",
        "runtime_layer": "AWS_Lambda" if IS_LAMBDA else "Local_Machine"
    }

# Main app mein master routing configuration inject ki
app.include_router(api_router)

# ─── Global Exception Handlers ────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error_code = getattr(exc, 'detail', 'UNKNOWN_ERROR')
    message = error_code if isinstance(error_code, str) else str(error_code)
    return error_response('HTTP_ERROR', message, status_code=exc.status_code)

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception caught on core loop: {exc}")
    return error_response(
        "INTERNAL_SERVER_ERROR",
        "An unexpected error occurred. Please try again later.",
        status_code=500,
    )

@app.get("/ui", response_class=HTMLResponse)
async def ui():
    ui_path = BASE_DIR / "bharatbot_ui2.html"
    if not ui_path.exists():
        return "<h1>UI file not found — place bharatbot_ui2.html in the same directory as main.py.</h1>"
    return ui_path.read_text(encoding="utf-8")

# 🚀 STEP 3: EXPORT MANGUM HANDLER
handler = Mangum(app, lifespan="off")
