# services/june-orchestrator/app.py
import os
import json
import uuid
import asyncio
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends
from authz import get_current_user
from firebase_admin import auth as fb_auth

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="June Orchestrator", version="1.0.0")
voice_router = APIRouter()

logger = logging.getLogger("orchestrator.voice")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
FIREBASE_PROJECT_ID    = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_WEB_API_KEY   = os.getenv("FIREBASE_WEB_API_KEY", "")  # optional; only if you added /v1/dev-token
INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_SHARED_SECRET", "")  # optional; only for dev helpers

# Downstream services
STT_WS_URL  = os.getenv("STT_WS_URL", "")        # e.g., wss://<stt-service>/ws
STT_HTTP_URL = os.getenv("STT_HTTP_URL") or (STT_WS_URL.replace("wss://", "https://").removesuffix("/ws") if STT_WS_URL else "")
TTS_URL     = os.getenv("TTS_URL", "")           # e.g., https://<tts-service>/v1/tts

# Audio defaults
DEFAULT_LOCALE        = os.getenv("DEFAULT_LOCALE", "en-US")
DEFAULT_STT_RATE      = int(os.getenv("DEFAULT_STT_RATE", "16000"))
DEFAULT_STT_ENCODING  = os.getenv("DEFAULT_STT_ENCODING", "pcm16")     # pcm16|opus (what your STT expects)
DEFAULT_TTS_ENCODING  = os.getenv("DEFAULT_TTS_ENCODING", "MP3")       # MP3|OGG_OPUS|LINEAR16

# Handshake + private STT options
STT_HANDSHAKE              = os.getenv("STT_HANDSHAKE", "start").lower()  # start|config|none
STT_REQUIRE_CLOUDRUN_AUTH  = os.getenv("STT_REQUIRE_CLOUDRUN_AUTH", "false").lower() == "true"

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

# Minimal config info (requires auth). Avoid leaking detailed config.
@app.get("/configz")
async def configz(user=Depends(get_current_user)):
    return {
        "ok": True,
        "project": FIREBASE_PROJECT_ID,
        "voice": {
            "locale": DEFAULT_LOCALE,
            "stt_rate": DEFAULT_STT_RATE,
            "stt_enc": DEFAULT_STT_ENCODING,
            "tts_enc": DEFAULT_TTS_ENCODING,
        },
    }

# -----------------------------------------------------------------------------
# Minimal chat endpoint the orchestrator can call to generate replies.
# Replace with your real chain/agent later.
# -----------------------------------------------------------------------------
@app.post("/v1/chat")
async def chat(payload: dict, user=Depends(get_current_user)):
    user_text = (payload or {}).get("user_input", "")
    # TODO: plug your LLM/agent here; for now, simple echo-style reply
    reply = f"You said: {user_text}".strip()
    return {"reply": reply}

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
async def _fetch_gcp_id_token(audience: str) -> str:
    """
    Get a Google-signed ID token for Cloud Run (audience = HTTPS base URL).
    Works only inside GCP (metadata server).
    """
    url = "http://metadata/computeMetadata/v1/instance/service-accounts/default/identity"
    headers = {"Metadata-Flavor": "Google"}
    params = {"audience": audience, "format": "full"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        return r.text.strip()

async def _llm_generate_reply_via_http(text: str, id_token: str, base_url: str = "http://127.0.0.1:8080") -> str:
    """
    Calls this same service's /v1/chat to reuse your existing chain/agent.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
            r = await client.post(
                f"{base_url}/v1/chat",
                headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
                json={"user_input": text},
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("reply") or "").strip()
    except Exception:
        logger.exception("[voice] /v1/chat failed; falling back")
        return f"You said: {text}"

async def _tts_stream(reply_text: str, locale: str, id_token: str, client_ws: WebSocket, turn_id: str):
    """
    Streams audio bytes from TTS to the WebSocket client.
    The RN client expects: 'tts.start' (with content_type), then raw audio chunks, then 'tts.done'.
    """
    if not TTS_URL:
        await client_ws.send_text(json.dumps({"type":"error", "code":"CONFIG", "message":"TTS_URL not set"}))
        return

    params = {"text": reply_text, "language_code": locale, "audio_encoding": DEFAULT_TTS_ENCODING}
    headers = {"Authorization": f"Bearer {id_token}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        async with client.stream("POST", TTS_URL, params=params, headers=headers) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "audio/mpeg")
            await client_ws.send_text(json.dumps({"type":"tts.start", "turn_id": turn_id, "content_type": ctype}))
            async for chunk in r.aiter_bytes(chunk_size=32768):
                if not chunk:
                    break
                await client_ws.send_bytes(chunk)
            await client_ws.send_text(json.dumps({"type":"tts.done", "turn_id": turn_id}))

# -----------------------------------------------------------------------------
# Voice bridge (client <-> STT; on final -> call LLM -> stream TTS)
# -----------------------------------------------------------------------------
@voice_router.websocket("/v1/voice")
async def voice_ws(ws: WebSocket):
    """
    Client connects here with:
      wss://<orchestrator>/v1/voice?token=<FIREBASE_ID_TOKEN>&locale=en-US
    Then it sends raw audio frames (pcm16 | opus). We forward to STT.
    """
    token: Optional[str] = ws.query_params.get("token")
    locale: str = ws.query_params.get("locale") or DEFAULT_LOCALE

    # Verify token BEFORE accepting the WebSocket
    if not token:
        await ws.close(code=4401)
        return
    try:
        # Validate Firebase ID token
        await asyncio.get_event_loop().run_in_executor(None, lambda: fb_auth.verify_id_token(token))
    except Exception:
        await ws.close(code=4401)
        return

    await ws.accept()

    try:
        await _stt_bridge(ws, token, locale, DEFAULT_STT_ENCODING)
    except Exception:
        logger.exception("[voice] unhandled")
        try:
            await ws.send_text(json.dumps({"type":"error","code":"VOICE","message":"internal error"}))
        except Exception:
            pass
        await ws.close(code=1011)

async def _stt_bridge(client_ws: WebSocket, id_token: str, locale: str, encoding: str):
    """
    Fan-in mic frames from client → STT; fan-out STT results → client.
    On 'final' transcripts, call /v1/chat, then stream TTS back to client.
    """
    if not STT_WS_URL:
        await client_ws.send_text(json.dumps({"type":"error","code":"CONFIG","message":"STT_WS_URL not set"}))
        return

    import websockets  # lazy import so container can start even if ws lib missing at build time
    from websockets.exceptions import InvalidStatusCode, ConnectionClosed

    q = f"?token={id_token}&lang={locale}&rate={DEFAULT_STT_RATE}&encoding={encoding}"
    uri = STT_WS_URL + q

    # Optional: Cloud Run IAM auth header if STT is private
    extra_headers = {}
    if STT_REQUIRE_CLOUDRUN_AUTH and STT_HTTP_URL:
        try:
            cr_id_token = await _fetch_gcp_id_token(STT_HTTP_URL)
            extra_headers["Authorization"] = f"Bearer {cr_id_token}"
        except Exception:
            logger.exception("[voice] Cloud Run ID token fetch failed")

    try:
        async with websockets.connect(uri, ping_interval=20, extra_headers=extra_headers) as stt_ws:
            # === REQUIRED by your STT: send START (or CONFIG) first ===
            try:
                if STT_HANDSHAKE == "start":
                    await stt_ws.send(json.dumps({
                        "type": "start",
                        "lang": locale,
                        "rate": DEFAULT_STT_RATE,
                        "encoding": encoding
                    }))
                elif STT_HANDSHAKE == "config":
                    await stt_ws.send(json.dumps({
                        "type": "config",
                        "lang": locale,
                        "rate": DEFAULT_STT_RATE,
                        "encoding": encoding
                    }))
                # if "none", send nothing
            except Exception:
                logger.exception("[voice] STT handshake send failed")

            async def from_client_to_stt():
                try:
                    while True:
                        message = await client_ws.receive()
                        if message.get("type") == "websocket.receive":
                            if message.get("bytes") is not None:
                                # forward raw audio frame to STT
                                await stt_ws.send(message["bytes"])
                            elif message.get("text"):
                                # reserve for future client control messages
                                pass
                        elif message.get("type") == "websocket.disconnect":
                            try:
                                await stt_ws.send(json.dumps({"type":"done"}))
                            except Exception:
                                pass
                            break
                except WebSocketDisconnect:
                    try:
                        await stt_ws.send(json.dumps({"type":"done"}))
                    except Exception:
                        pass

            async def from_stt_to_client_and_llm():
                try:
                    async for stt_msg in stt_ws:
                        if isinstance(stt_msg, bytes):
                            # ignore binary from STT
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
                            text_in = data.get("text", "") or ""
                            turn_id = str(uuid.uuid4())
                            await client_ws.send_text(json.dumps({"type": "stt.final", "text": text_in, "turn_id": turn_id}))

                            # Generate reply via our own /v1/chat
                            reply = await _llm_generate_reply_via_http(text_in, id_token)
                            await client_ws.send_text(json.dumps({"type":"llm.reply","text":reply,"turn_id":turn_id}))

                            # Stream synthesized audio back to the client
                            await _tts_stream(reply, locale, id_token, client_ws, turn_id)

                except ConnectionClosed as e:
                    logger.error(f"[voice] STT WS closed: code={getattr(e, 'code', None)} reason={getattr(e, 'reason', '')}")
                    await client_ws.send_text(json.dumps({"type":"error","code":"STT_CLOSED","message":f"stt closed {getattr(e,'code',None)} {getattr(e,'reason','')}".strip()}))
                except Exception:
                    logger.exception("[voice] STT bridge failed")
                    await client_ws.send_text(json.dumps({"type":"error","code":"STT","message":"bridge error"}))

            await asyncio.gather(from_client_to_stt(), from_stt_to_client_and_llm())

    except InvalidStatusCode as e:
        logger.error(f"[voice] STT handshake rejected: {e.status_code} uri={uri}")
        await client_ws.send_text(json.dumps({"type":"error","code":"STT_CONNECT","message":f"http {e.status_code} during ws handshake"}))
    except Exception:
        logger.exception("[voice] STT connect failed")
        await client_ws.send_text(json.dumps({"type":"error","code":"STT","message":"connect failed"}))

# -----------------------------------------------------------------------------
# Include router
# -----------------------------------------------------------------------------
app.include_router(voice_router)
