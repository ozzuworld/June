# voice_ws.py — Server-orchestrated voice loop (hybrid RN/Web)
# - RN: set ORCH_STREAM_TTS=false and let the client fetch TTS over HTTP
# - Web: set ORCH_STREAM_TTS=true to stream TTS bytes over the same WS
#
# Env expected:
#   FIREBASE_PROJECT_ID
#   STT_WS_URL=wss://<stt>/ws
#   TTS_URL=https://<tts>/v1/tts            # for POST; can also be a GET endpoint
#   TTS_HTTP_METHOD=POST|GET                # default POST
#   DEFAULT_LOCALE=en-US
#   DEFAULT_STT_RATE=16000
#   DEFAULT_STT_ENCODING=pcm16
#   DEFAULT_TTS_ENCODING=MP3
#   ORCH_STREAM_TTS=true|false              # false for RN
#
# Requires: httpx, websockets

import os, json, uuid, asyncio, logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import httpx

voice_router = APIRouter()
logger = logging.getLogger("orchestrator.voice")

# ---- Configuration ----
STT_WS_URL = os.getenv("STT_WS_URL", "")
TTS_URL = os.getenv("TTS_URL", "")  # optional when ORCH_STREAM_TTS=false
TTS_HTTP_METHOD = os.getenv("TTS_HTTP_METHOD", "POST").upper()

DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en-US")
DEFAULT_STT_RATE = int(os.getenv("DEFAULT_STT_RATE", "16000"))
DEFAULT_STT_ENCODING = os.getenv("DEFAULT_STT_ENCODING", "pcm16")
DEFAULT_TTS_ENCODING = os.getenv("DEFAULT_TTS_ENCODING", "MP3")
ORCH_STREAM_TTS = os.getenv("ORCH_STREAM_TTS", "false").lower() == "true"

PORT = os.getenv("PORT", "8080")
LOCAL_BASE_URL = f"http://127.0.0.1:{PORT}"

# ---- Helpers ----

async def _llm_via_http(text: str, id_token: str) -> str:
    """Call our own /v1/chat so we reuse your existing chain/agent."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
            r = await client.post(
                f"{LOCAL_BASE_URL}/v1/chat",
                headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
                json={"user_input": text},
            )
            r.raise_for_status()
            return (r.json().get("reply") or "").strip()
    except Exception:
        logger.exception("[voice] /v1/chat failed")
        # Fallback keeps the loop alive
        return f"You said: {text}"

async def _tts_stream(reply_text: str, locale: str, id_token: str, client_ws: WebSocket, turn_id: str):
    """Optionally stream TTS bytes to the client over this WS (for web)."""
    if not TTS_URL:
        await client_ws.send_text(json.dumps({"type": "error", "code": "CONFIG", "message": "TTS_URL not set"}))
        return

    # We keep using query params so existing TTS servers work unchanged.
    params = {"text": reply_text, "language_code": locale, "audio_encoding": DEFAULT_TTS_ENCODING}
    headers = {"Authorization": f"Bearer {id_token}"}

    method = TTS_HTTP_METHOD if TTS_HTTP_METHOD in ("GET", "POST") else "POST"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        request_args = {"method": method, "url": TTS_URL, "params": params, "headers": headers}
        async with client.stream(**request_args) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "audio/mpeg" if DEFAULT_TTS_ENCODING.upper() == "MP3" else "application/octet-stream")
            await client_ws.send_text(json.dumps({"type": "tts.start", "turn_id": turn_id, "content_type": ctype}))
            async for chunk in r.aiter_bytes(chunk_size=32768):
                if not chunk:
                    break
                await client_ws.send_bytes(chunk)
            await client_ws.send_text(json.dumps({"type": "tts.done", "turn_id": turn_id}))

async def _stt_bridge(client_ws: WebSocket, id_token: str, locale: str, encoding: str):
    """Mic frames client→STT; STT results→client; on final→LLM (+ optional TTS stream)."""
    if not STT_WS_URL:
        await client_ws.send_text(json.dumps({"type": "error", "code": "CONFIG", "message": "STT_WS_URL not set"}))
        return

    import websockets  # lazy import
    q = f"?token={id_token}&lang={locale}&rate={DEFAULT_STT_RATE}&encoding={encoding}"
    uri = STT_WS_URL + q

    async with websockets.connect(uri, ping_interval=20) as stt_ws:
        # Send optional config first (ignore if STT doesn't use it)
        try:
            await stt_ws.send(json.dumps({"type": "config", "lang": locale, "rate": DEFAULT_STT_RATE, "encoding": encoding}))
        except Exception:
            pass

        async def from_client_to_stt():
            try:
                while True:
                    message = await client_ws.receive()
                    if message.get("type") == "websocket.receive":
                        if message.get("bytes") is not None:
                            await stt_ws.send(message["bytes"])
                        elif message.get("text"):
                            # place for future control messages
                            pass
                    elif message.get("type") == "websocket.disconnect":
                        try:
                            await stt_ws.send(json.dumps({"type": "done"}))
                        except Exception:
                            pass
                        break
            except WebSocketDisconnect:
                try:
                    await stt_ws.send(json.dumps({"type": "done"}))
                except Exception:
                    pass

        async def from_stt_to_client_and_llm():
            try:
                async for stt_msg in stt_ws:
                    if isinstance(stt_msg, bytes):
                        continue
                    data = json.loads(stt_msg)
                    t = data.get("type")
                    if t == "partial":
                        await client_ws.send_text(json.dumps({
                            "type": "stt.partial",
                            "text": data.get("text", ""),
                            "start_ms": data.get("start_ms"),
                            "end_ms": data.get("end_ms"),
                        }))
                    elif t == "final":
                        text_in = data.get("text", "")
                        turn_id = str(uuid.uuid4())
                        await client_ws.send_text(json.dumps({"type": "stt.final", "text": text_in, "turn_id": turn_id}))

                        # LLM reply
                        reply = await _llm_via_http(text_in, id_token)
                        await client_ws.send_text(json.dumps({"type": "llm.reply", "text": reply, "turn_id": turn_id}))

                        # Stream TTS only if enabled (RN should set ORCH_STREAM_TTS=false)
                        if ORCH_STREAM_TTS:
                            await _tts_stream(reply, locale, id_token, client_ws, turn_id)
            except Exception:
                logger.exception("[voice] STT bridge failed")
                await client_ws.send_text(json.dumps({"type": "error", "code": "STT", "message": "bridge error"}))

        await asyncio.gather(from_client_to_stt(), from_stt_to_client_and_llm())

# ---- Routes ----

@voice_router.websocket("/v1/voice")
async def voice_ws(ws: WebSocket):
    # Expect ?token and ?locale
    token = ws.query_params.get("token")
    locale = ws.query_params.get("locale") or DEFAULT_LOCALE

    await ws.accept()
    if not token:
        await ws.send_text(json.dumps({"type": "error", "code": "AUTH", "message": "Missing ?token"}))
        await ws.close(code=4401)
        return

    try:
        await _stt_bridge(ws, token, locale, DEFAULT_STT_ENCODING)
    except Exception:
        logger.exception("[voice] unhandled")
        try:
            await ws.send_text(json.dumps({"type": "error", "code": "VOICE", "message": "internal error"}))
        except Exception:
            pass
        await ws.close(code=1011)

@voice_router.get("/healthz")
async def healthz():
    return {"ok": True}
