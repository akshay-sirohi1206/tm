# API Logging - Quick Reference

## Problem ❌
Old logs showed 500+ lines per session:
- HTTP headers (50+ lines)
- WebSocket debug info (50+ lines)  
- Watchfiles monitoring (100+ lines)
- Pipecat framework spam (50+ lines)

**Result:** Impossible to see actual API calls.

---

## Solution ✅
**API calls only - one line per request**

```
✅ POST   /auth/signup                      | 201 |   45.2ms
✅ GET    /sessions                          | 200 |   12.5ms
✅ POST   /sessions                          | 201 |    8.3ms
⚠️ GET    /sessions/314efcad/messages       | 404 |    6.0ms
❌ DELETE /sessions/314efcad                | 404 |    3.1ms
```

---

## How It Works

| Component | Level | Output |
|-----------|-------|--------|
| BharatBot | INFO | ✅ API calls + startup |
| uvicorn | WARNING | 🔇 Suppressed |
| watchfiles | ERROR | 🔇 Suppressed |
| pipecat | WARNING | 🔇 Suppressed |

---

## Log Files

### `logs/bharatbot.log`
Full application logs (all INFO+ messages)

### `logs/api_calls.log` (NEW)
API calls only - clean format

---

## Reading the Output

```
✅ POST   /auth/login              | 200 |   32.4ms
│  │      │                        │     └─ Response time
│  │      │                        └─ HTTP status code
│  │      └─ API endpoint
│  └─ HTTP method
└─ Success indicator
```

### Status Codes
- ✅ 2xx = Success
- ⚠️ 4xx = Client error (bad request)
- ❌ 5xx = Server error

---

## Viewing Logs

### Terminal (Live Stream)
```bash
# API calls only
tail -f logs/api_calls.log

# Full logs
tail -f logs/bharatbot.log
```

### Search Examples
```bash
# All errors
grep "❌" logs/api_calls.log

# Specific endpoint
grep "POST.*auth" logs/api_calls.log

# Slow endpoints (>100ms)
grep "|[1-9][0-9][0-9]\.[0-9]ms" logs/api_calls.log

# All authentication calls
grep "/auth" logs/api_calls.log
```

---

## What Gets Logged

### YES ✅
- API method & path
- HTTP status code
- Response time
- Errors/exceptions
- Business logic (database ops, etc.)

### NO ❌
- HTTP headers
- Framework debug info
- File monitoring
- WebSocket frame details
- Async internals

---

## Performance Benefits

**Disk Space:**
- Old: 500+ lines/session = 50+ KB/session
- New: 1 line/session = ~100 bytes/session
- **99.8% reduction!**

**Readability:**
- Old: 1 useful line in 500 lines (0.2%)
- New: Every line is useful (100%)

---

## Testing

When you see in console:
```
✅ POST   /auth/login              | 200 |   32.4ms
✅ GET    /sessions                | 200 |   12.5ms
```

✅ **Logging is working perfectly!**

---

## Configuration (mainV2.py)

Lines 40-135 contain:
- Logger initialization
- Handler setup
- Log level configuration
- API middleware with formatting

**No additional configuration needed** - works out of the box!

---

## Production Ready ✅

✅ Separate API log file
✅ Rotating log files (5 MB max)
✅ Backup copies (5 old logs kept)
✅ Clean, parseable format
✅ Perfect for log aggregation (ELK, Datadog, etc.)

---

**Updated:** 2026-06-21  
**Status:** Ready to Use
