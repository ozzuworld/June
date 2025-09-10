# June/services/june-stt/app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
import logging, json
import base64
import time
from typing import Optional

from authz import verify_token_query
from shared.auth_service import require_service_auth

app = FastAPI(title="June STT Service", version="1.0.0")
logger = logging.getLogger("uvicorn.error")

# -----------------------------------------------------------------------------
# Health endpoint
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "june-stt"}

# -----------------------------------------------------------------------------
# Service-to-Service Transcription Endpoint (NEW)
# -----------------------------------------------------------------------------
@app.post("/v1/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("en-US"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    Transcribe audio endpoint for service-to-service communication
    Protected by service authentication
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"Transcription request from service: {calling_service}")
    
    try:
        # Read audio file
        audio_content = await audio.read()
        logger.info(f"Received audio: {len(audio_content)} bytes, language: {language}")
        
        # TODO: Implement actual STT processing here
        # For now, return a mock response
        # In production, you would:
        # 1. Process the audio with Google Cloud Speech-to-Text
        # 2. Or use another STT service
        # 3. Return the transcription result
        
        # Mock transcription result
        mock_text = f"[Mock transcription] Audio received with {len(audio_content)} bytes in {language}"
        
        return {
            "text": mock_text,
            "language": language,
            "confidence": 0.95,
            "duration": len(audio_content) / 16000,  # Approximate duration
            "processed_by": "june-stt",
            "caller": calling_service
        }
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Transcription failed: {str(e)}"}
        )

# -----------------------------------------------------------------------------
# WebSocket endpoint for real-time STT (EXISTING)
# -----------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    # Keep your existing WebSocket implementation
    # This handles real-time audio streaming from clients
    
    # 1) Verify token from query *before* accept
    token = ws.query_params.get("token")
    try:
        claims = verify_token_query(token)     # Firebase token validation
    except Exception:
        await ws.close(code=4401)
        logger.info("[ws] close 4401 (unauthorized)")
        return

    # 2) Accept the connection
    await ws.accept()
    uid = claims.get("uid")
    logger.info(f"[ws] accepted uid={uid}")

    try:
        # 3) Expect a JSON "start" control message first
        first = await ws.receive_text()
        try:
            ctrl = json.loads(first)
        except Exception:
            await ws.close(code=4400)
            logger.info("[ws] close 4400 (invalid JSON start)")
            return

        if ctrl.get("type") != "start":
            await ws.close(code=4400)
            logger.info("[ws] close 4400 (missing start)")
            return

        lang = ctrl.get("language_code", "en-US")
        rate = int(ctrl.get("sample_rate_hz", 16000))
        enc  = ctrl.get("encoding", "LINEAR16")
        logger.info(f"[ws] start uid={uid} lang={lang} rate={rate} enc={enc}")

        # 4) Main loop: receive audio frames (binary) or control messages
        while True:
            msg = await ws.receive()
            if "type" in msg and msg["type"] == "websocket.disconnect":
                logger.info(f"[ws] disconnect uid={uid}")
                break

            if "text" in msg:
                # Handle control messages like "stop"
                try:
                    obj = json.loads(msg["text"])
                    if obj.get("type") == "stop":
                        logger.info(f"[ws] stop uid={uid}")
                        await ws.close(code=1000)
                        break
                except Exception:
                    pass
                continue

            if "bytes" in msg:
                audio_bytes = msg["bytes"]
                
                # TODO: Process audio_bytes with real STT
                # For now, send back mock partial/final results
                
                # Mock partial result
                await ws.send_text(json.dumps({
                    "type": "partial",
                    "text": f"Processing audio chunk ({len(audio_bytes)} bytes)...",
                    "start_ms": 0,
                    "end_ms": 1000
                }))
                
                # Occasionally send a "final" result
                if len(audio_bytes) > 1000:  # Arbitrary condition for demo
                    await ws.send_text(json.dumps({
                        "type": "final",
                        "text": f"Mock transcription of {len(audio_bytes)} bytes",
                        "start_ms": 0,
                        "end_ms": 2000
                    }))
                
    except WebSocketDisconnect:
        logger.info(f"[ws] disconnected uid={uid}")
    except Exception:
        logger.exception("[ws] error")
        try:
            await ws.close(code=1011)  # internal error
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Test endpoint to verify service authentication
# -----------------------------------------------------------------------------
@app.get("/v1/test-auth")
async def test_auth(service_auth_data: dict = Depends(require_service_auth)):
    """Test endpoint to verify service authentication is working"""
    return {
        "message": "Service authentication successful",
        "caller": service_auth_data.get("client_id"),
        "scopes": service_auth_data.get("scopes", []),
        "service": "june-stt"
    }

# Add this route if it doesn't exist  
@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "june-stt", "timestamp": time.time()}

# Also add a root route
@app.get("/")
async def root():
    return {"service": "june-stt", "status": "running"}