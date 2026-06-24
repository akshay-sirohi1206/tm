"""
Standard response envelope helpers — wraps all API responses in a consistent shape.
...
"""

import json
from datetime import datetime, date, timezone
from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse


class _DateTimeEncoder(json.JSONEncoder):
    """Serialize datetime/date objects to ISO 8601 strings."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def _jsonable(data: Any) -> Any:
    """Run data through the custom encoder so JSONResponse never chokes on datetimes."""
    return json.loads(json.dumps(data, cls=_DateTimeEncoder))


def get_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def success_response(
    data: Any,
    status_code: int = 200,
    meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    if meta is None:
        meta = {}
    meta["timestamp"] = get_iso_timestamp()

    return JSONResponse(
        status_code=status_code,
        content=_jsonable({          # ← only change here
            "success": True,
            "data": data,
            "error": None,
            "meta": meta,
        })
    )


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    if meta is None:
        meta = {}
    meta["timestamp"] = get_iso_timestamp()

    return JSONResponse(
        status_code=status_code,
        content=_jsonable({          # ← and here
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
            "meta": meta,
        })
    )
    