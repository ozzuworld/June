# app.py — FastAPI app with /v1/chat and server-orchestrated /v1/voice (WS)
import os, json, uuid, asyncio, logging
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import APIRouter
from pydantic import BaseModel
from voice_ws import voice_router

# Auth helper (shared). If you don't have this file yet, use the authz.py I sent earlier.
from authz import get_current_user

logger = logging.getLogger("orchestrator")

# ---------- Configuration ----------
STT_WS_URL = os.getenv("STT_WS_URL", "")   # e.g. wss://<stt-service>/ws
TTS_URL    = os.getenv("TTS_URL", "")      # e.g. https://<tts-service>/speak

DEFAULT_LOCALE        = os.getenv("DEFAULT_LOCALE", "en-US")
DEFAULT_STT_RATE      = int(os.getenv("DEFAULT_STT_RATE", "16000"))
DEFAULT_STT_ENCODING  = os.getenv("DEFAULT_STT_ENCODING", "opus")     # opus|pcm16
DEFAULT_TTS_ENCODING  = os.getenv("DEFAULT_TTS_ENCODING", "OGG_OPUS") # OGG_OPUS|MP3|LINEAR16

PORT = os.getenv("PORT", "8080")  # for local loopback to our own HTTP endpoint
LOCAL_BASE_URL = f"http://127.0.0.1:{PORT}"

# ---------- FastAPI app ----------
app = FastAPI()
app.include_router(voice_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Health ----------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

# ---------- /v1/chat (HTTP) ----------
class ChatIn(BaseModel):
    user_input: str

async def _llm_generate_reply(user_text: str, locale: str) -> str:
    """
    Stub LLM. Replace with your real chain/agent.
    If you already have a complex chain in this service, keep your existing /v1/chat.
    """
    return f"You said: {user_text}"

@app.post("/v1/chat")
async def chat(req: ChatIn, user=Depends(get_current_user)):
    reply = await _llm_generate_reply(req.user_input, DEFAULT_LOCALE)
    return {"reply": reply}

# ---------- Voice router (WebSocket) ----------
voice_router = APIRouter()

async def _tts_stream(reply_text: str, locale: str, id_token: str, client_ws: WebSocket, turn_id: str):
    if not TTS_URL:
        await client_ws.send_text(json.dumps({"type":"error", "code":"CONFIG", "message":"TTS_URL not set"}))
        return
    params = {"text": reply_text, "language_code": locale, "audio_encoding": DEFAULT_TTS_ENCODING}
    headers = {"Authorization": f"Bearer {id_token}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        async with client.stream("GET", TTS_URL, params=params, headers=headers) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "audio/ogg")
            await client_ws.send_text(json.dumps({"type":"tts.start", "turn_id": turn_id, "content_type": ctype}))
            async for chunk in r.aiter_bytes(chunk_size=32768):  # ~32KB
                if not chunk:
                    break
                await client_ws.send_bytes(chunk)
            await client_ws.send_text(json.dumps({"type":"tts.done", "turn_id": turn_id}))

async def _llm_via_http(text: str, id_token: str) -> str:
    """Call our own HTTP /v1/chat so we reuse your existing chain if you swap the stub."""
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
        logger.exception("[voice] /v1/chat failed; falling back")
        return await _llm_generate_reply(text, DEFAULT_LOCALE)

async def _stt_bridge(client_ws: WebSocket, id_token: str, locale: str, encoding: str):
    """Fan-in mic frames from client → STT; fan-out STT results → client; on final → LLM+TTS."""
    if not STT_WS_URL:
        await client_ws.send_text(json.dumps({"type":"error", "code":"CONFIG", "message":"STT_WS_URL not set"}))
        return

    import websockets  # lazy import
    q = f"?token={id_token}&lang={locale}&rate={DEFAULT_STT_RATE}&encoding={encoding}"
    uri = STT_WS_URL + q

    async with websockets.connect(uri, ping_interval=20) as stt_ws:
        try:
            await stt_ws.send(json.dumps({"type":"config", "lang": locale, "rate": DEFAULT_STT_RATE, "encoding": encoding}))
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
                            # handle client.control if you add it later
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
                        reply = await _llm_via_http(text_in, id_token)
                        await client_ws.send_text(json.dumps({"type": "llm.reply", "text": reply, "turn_id": turn_id}))
                        await _tts_stream(reply, locale, id_token, client_ws, turn_id)
            except Exception:
                logger.exception("[voice] STT bridge failed")
                await client_ws.send_text(json.dumps({"type":"error","code":"STT","message":"bridge error"}))

        await asyncio.gather(from_client_to_stt(), from_stt_to_client_and_llm())

@voice_router.websocket("/v1/voice")
async def voice_ws(ws: WebSocket):
    # Expect ?token and optional ?locale
    token = ws.query_params.get("token")
    locale = ws.query_params.get("locale") or DEFAULT_LOCALE

    await ws.accept()
    if not token:
        await ws.send_text(json.dumps({"type":"error","code":"AUTH","message":"Missing ?token"}))
        await ws.close(code=4401)
        return

    try:
        await _stt_bridge(ws, token, locale, DEFAULT_STT_ENCODING)
    except Exception:
        logger.exception("[voice] unhandled")
        try:
            await ws.send_text(json.dumps({"type":"error","code":"VOICE","message":"internal error"}))
        except Exception:
            pass
        await ws.close(code=1011)

# Register router (robust; avoids NameError)
app.include_router(voice_router)
