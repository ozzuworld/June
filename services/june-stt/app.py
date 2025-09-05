# june-stt/app.py (relevant parts)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import logging, json

from authz import verify_token_query

app = FastAPI()
logger = logging.getLogger("uvicorn.error")

@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    # 1) Verify token from query *before* accept
    token = ws.query_params.get("token")
    try:
        claims = verify_token_query(token)     # may raise HTTPException
    except Exception:
        # IMPORTANT: don’t let the exception propagate — close with WS code
        # 4401 is a common custom “Unauthorized” code
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
            await ws.close(code=4400)  # bad request
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
                # maybe "stop" or other control messages
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
                # TODO: feed to STT recognizer; send interim/final back
                # await ws.send_text(json.dumps({"type":"partial","text":"..."}))
                # Example placeholder:
                # await ws.send_text(json.dumps({"type":"debug","bytes": len(audio_bytes)}))
                continue

    except WebSocketDisconnect:
        logger.info(f"[ws] disconnected uid={uid}")
    except Exception:
        logger.exception("[ws] error")
        try:
            await ws.close(code=1011)  # internal error
        except Exception:
            pass
