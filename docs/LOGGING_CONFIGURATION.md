# Logging Configuration - API Calls Only

## Problem (Peechle Setup)
Too many verbose logs from:
- ✅ uvicorn (HTTP headers - 100+ lines per request)
- ✅ watchfiles (File monitoring - every file change logged)
- ✅ pipecat (Framework debug info)
- ✅ urllib, asyncio, etc.

**Result:** Logs become unreadable, hard to debug API issues.

---

## Solution (New Setup)

### 1. Suppress Verbose Loggers

```python
QUIET_LOGGERS = {
    "uvicorn": logging.WARNING,           # Suppress HTTP header logs
    "uvicorn.error": logging.WARNING,     # No WebSocket debug logs
    "uvicorn.access": logging.WARNING,    # No access logs to console
    "watchfiles": logging.ERROR,          # Suppress file change logs
    "watchfiles.main": logging.ERROR,     # No reload detection spam
    "pipecat": logging.WARNING,           # Still log errors only
    "pipecat.pipeline": logging.WARNING,
    "pipecat.utils": logging.WARNING,
}
```

**Effect:** No more spam, only actual errors from these libraries.

### 2. Two Log Files

#### `logs/bharatbot.log` (Main Log)
- All messages from BharatBot application
- Application startup/shutdown
- Database operations
- Business logic events
- Errors and warnings

#### `logs/api_calls.log` (API-Only Log)
- Clean API request/response logs
- No application debug info
- Perfect for monitoring API traffic
- Easy to parse and analyze

### 3. Console Output (Terminal)
Shows only API calls in clean format:

```
✅ POST   /auth/signup                      | 201 |   45.2ms
✅ GET    /sessions                          | 200 |   12.5ms
✅ POST   /sessions                          | 201 |   8.3ms
⚠️ GET    /sessions/invalid-id              | 404 |   3.1ms
❌ POST   /chat/error                        | 500 |   156.7ms
```

---

## Log Format

### API Call Log Format
```
TIMESTAMP [METHOD] [PATH] [STATUS] [RESPONSE_TIME]
```

Example:
```
2026-06-21 22:12:23 ✅ POST   /auth/login                         | 200 |   32.4ms
2026-06-21 22:12:24 ✅ POST   /sessions                           | 201 |    5.0ms
2026-06-21 22:12:25 ⚠️ GET    /sessions/314efcad/messages         | 404 |    6.0ms
2026-06-21 22:12:35 ❌ DELETE /sessions/314efcad                  | 404 |    3.1ms
```

**Status Indicators:**
- ✅ 2xx (Success)
- ⚠️ 4xx (Client Error)
- ❌ 5xx (Server Error)

---

## Log Levels Used

| Level | Used For | Console | File | API Log |
|-------|----------|---------|------|---------|
| DEBUG | (DISABLED) | ❌ | ❌ | ❌ |
| INFO | API calls, startup | ✅ | ✅ | ✅ |
| WARNING | uvicorn, pipecat errors | ❌ | ✅ | ❌ |
| ERROR | Application errors | ✅ | ✅ | ❌ |
| CRITICAL | System failures | ✅ | ✅ | ❌ |

---

## Configuration Details

### Root Logger
```
Level: WARNING
Handlers: Console + Main File Log
```

### BharatBot Logger
```
Level: INFO
Handlers: Console + Main File Log + API File Log
```

### Third-party Loggers
```
Level: WARNING (uvicorn, watchfiles, pipecat)
Propagate: False (don't send to root)
```

---

## Results

### Before Changes
```
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < host: localhost:8000
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < connection: Upgrade
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < pragma: no-cache
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < cache-control: no-cache
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < user-agent: Mozilla/5.0...
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < upgrade: websocket
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < sec-websocket-version: 13
2026-06-21 22:12:22 [DEBUG] uvicorn.error: < accept-encoding: gzip, deflate, br, zstd
... (100 more lines of HTTP headers)
2026-06-21 22:12:23 [DEBUG] watchfiles.main: 5 changes detected...
2026-06-21 22:12:23 [DEBUG] watchfiles.main: 1 change detected...
... (50 more watchfiles messages)
```

**Problem:** Hard to see actual API calls in 500+ lines of spam.

### After Changes
```
✅ POST   /auth/signup                      | 201 |   45.2ms
✅ GET    /sessions                          | 200 |   12.5ms
✅ POST   /sessions                          | 201 |    8.3ms
⚠️ GET    /sessions/314efcad/messages       | 404 |    6.0ms
❌ DELETE /sessions/314efcad                | 404 |    3.1ms
```

**Result:** Clear, concise, easy to understand. Perfect for debugging.

---

## How to Use

### View API Calls Only
```bash
# Console output (live)
tail -f logs/api_calls.log

# Or from application output
```

### View All Logs
```bash
tail -f logs/bharatbot.log
```

### Search for API Errors
```bash
# All 4xx errors
grep "⚠️" logs/api_calls.log

# All 5xx errors  
grep "❌" logs/api_calls.log

# Specific endpoint
grep "POST.*auth" logs/api_calls.log
```

### Monitor Performance
```bash
# Slowest calls (last column is response time)
sort -k5 -rn logs/api_calls.log | head -20
```

---

## What Gets Logged

### Logged (Helpful)
✅ API requests (method, path, status, time)
✅ Authentication events
✅ Session creation/deletion
✅ Error stack traces
✅ Database operations (in service layer)
✅ External API calls (AWS Bedrock, S3)

### NOT Logged (Spam)
❌ HTTP headers from uvicorn
❌ File monitoring changes (watchfiles)
❌ Framework debug info (pipecat internals)
❌ WebSocket frame details
❌ Async event loop details

---

## Environment Variables

To control logging at runtime:

```bash
# Log level for BharatBot (default: INFO)
export LOG_LEVEL=DEBUG  # More detail
export LOG_LEVEL=WARNING  # Less detail

# Disable colored output (for production logs)
export NO_COLOR=1
```

---

## Production Recommendations

1. **Set level to WARNING** (suppress INFO logs on production)
2. **Use log aggregation** (send logs to ELK, Datadog, etc.)
3. **Monitor slow endpoints** (queries > 100ms)
4. **Alert on errors** (5xx responses)
5. **Archive old logs** (monthly rotation)

---

## Summary

✅ **Old Setup:**
- Generated 500+ lines per session
- Impossible to debug
- File size grows rapidly
- Console output unreadable

✅ **New Setup:**
- Only API calls logged
- One line per request
- Easy to analyze
- Perfect for monitoring

🎯 **Result:** Clean, focused logging that shows exactly what you need to know.

---

Generated: 2026-06-21  
Logging Version: 2.0 (API-Focused)
