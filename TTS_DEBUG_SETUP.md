# TTS DEBUG SETUP - URGENT DEBUGGING

## What This Does

The `debug_middleware.py` file will log EVERY SINGLE REQUEST that hits your TTS service so we can see:

1. **Is the orchestrator even reaching the TTS service?**
2. **What exactly is being sent in the request?**
3. **Where is the connection failing?**

## How to Use

### Step 1: Add to your TTS main.py

In your `services/june-tts/main.py` or `app.py`, add these imports at the top:

```python
from debug_middleware import TTSDebugMiddleware, debug_network_status
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
debug_logger = logging.getLogger("TTS-DEBUG")
```

### Step 2: Add the middleware to your FastAPI app

```python
from fastapi import FastAPI

app = FastAPI()

# ADD THIS LINE - this will log every request
app.add_middleware(TTSDebugMiddleware)
```

### Step 3: Add startup debugging

```python
@app.on_event("startup")
async def startup_debug():
    debug_logger.info("🚀 TTS SERVICE STARTING WITH FULL DEBUG MODE")
    debug_network_status()
    debug_logger.info("🔍 All incoming requests will be logged in detail")
```

### Step 4: Add to your health endpoint

```python
@app.get("/health")
async def health():
    debug_logger.info("💚 HEALTH CHECK ENDPOINT HIT")
    return {"status": "healthy", "debug": "enabled"}
```

## What You'll See

When the orchestrator tries to connect, you'll see logs like:

```
============================================================
🔥 NEW REQUEST RECEIVED
   Timestamp: 2025-11-05 19:09:57
   Method: POST
   URL: http://june-tts:8000/synthesize
   Path: /synthesize
   Client: 10.244.0.123:45678
   User-Agent: python-httpx/0.25.0
   Content-Type: application/json
   Content-Length: 156
   All Headers:
     host: june-tts:8000
     content-type: application/json
     content-length: 156
   Body Size: 156 bytes
   Body Content: {"text": "Good morning! How...", "voice": "英文女", "mode": "sft"}
🟡 PROCESSING REQUEST...
✅ REQUEST SUCCESSFUL
   Status Code: 200
   Process Time: 0.123 seconds
============================================================
```

## If No Logs Appear

If you don't see ANY request logs when the orchestrator tries to connect, then:

1. **The orchestrator is NOT reaching your TTS service**
2. **The URL configuration is wrong**
3. **Network connectivity issue**

## Quick Test

After adding the debug middleware, test it manually:

```bash
curl -X POST http://localhost:8000/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "test", "voice": "test", "mode": "sft"}'
```

You should see detailed logs in your TTS service output.

## NOW RESTART YOUR TTS SERVICE AND WATCH THE LOGS!

This will show us exactly what's happening when the orchestrator tries to connect.