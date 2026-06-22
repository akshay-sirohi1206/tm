"""
Standard response envelope helpers — wraps all API responses in a consistent shape.

Success:
  {
    "success": true,
    "data": { ... },
    "error": null,
    "meta": { "timestamp": "2024-01-01T12:00:00Z" }
  }

Error:
  {
    "success": false,
    "data": null,
    "error": { "code": "...", "message": "..." },
    "meta": { "timestamp": "2024-01-01T12:00:00Z" }
  }
"""

from datetime import datetime, timezone
from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse


def get_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def success_response(
    data: Any,
    status_code: int = 200,
    meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Wrap successful response in standard envelope.

    Args:
        data: The response payload (will be nested under 'data' key)
        status_code: HTTP status code
        meta: Optional metadata dict (timestamp is added automatically)
    """
    if meta is None:
        meta = {}

    meta["timestamp"] = get_iso_timestamp()

    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "error": None,
            "meta": meta,
        }
    )


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Wrap error response in standard envelope.

    Args:
        code: Machine-readable error code (e.g., 'INVALID_EMAIL', 'SESSION_NOT_FOUND')
        message: Human-readable error message
        status_code: HTTP status code
        meta: Optional metadata dict (timestamp is added automatically)
    """
    if meta is None:
        meta = {}

    meta["timestamp"] = get_iso_timestamp()

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
            },
            "meta": meta,
        }
    )
