# unitest/stt_test.py
import os, sys, json, asyncio, wave
import requests, websockets
from dotenv import load_dotenv
import numpy as np

load_dotenv()

BASE = os.getenv("STT_BASE")                # e.g. wss://june-stt-....run.app
PATH = os.getenv("STT_PATH", "/ws")
API_KEY = os.getenv("FIREBASE_API_KEY")
EMAIL = os.getenv("FIREBASE_TEST_EMAIL")
PASSWORD = os.getenv("FIREBASE_TEST_PASSWORD")

LANG = os.getenv("STT_LANG", "en-US")
RATE = int(os.getenv("STT_RATE", "16000"))
WAV  = os.getenv("STT_WAV")                 # optional, else mic

def require(name, val):
    if not val:
        print(f"Missing {name}", file=sys.stderr); sys.exit(2)
    return val

def get_id_token(api_key, email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    r = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return r.json()["idToken"]

async def stream_wav(ws, wav_path, rate):
    with wave.open(wav_path, "rb") as w:
        ch, sr, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        if ch != 1 or sr != rate or width != 2:
            print(f"⚠️ Expected mono 16-bit @{rate}Hz, got {ch}ch {width*8}-bit @{sr}Hz", file=sys.stderr)
        frames = int(rate * 0.1)  # 100ms
        while True:
            data = w.readframes(frames)
            if not data:
                break
            await ws.send(data)
            await asyncio.sleep(0.1)

async def stream_mic(ws, rate):
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice not installed. Set STT_WAV to a file.", file=sys.stderr)
        sys.exit(2)
    frames = int(rate * 0.1)
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16"):
        while True:
            audio = sd.rec(frames, samplerate=rate, channels=1, dtype="int16")
            sd.wait()
            await ws.send(audio.tobytes())

async def run():
    token = get_id_token(
        require("FIREBASE_API_KEY", API_KEY),
        require("FIREBASE_TEST_EMAIL", EMAIL),
        require("FIREBASE_TEST_PASSWORD", PASSWORD),
    )
    url = f"{BASE.rstrip('/')}{PATH if PATH.startswith('/') else '/'+PATH}?token={token}"

    async with websockets.connect(url, ping_interval=20, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "start",
            "language_code": LANG,
            "sample_rate_hz": RATE,
            "encoding": "LINEAR16"
        }))
        print("✅ Connected. Streaming audio...")

        async def sender():
            if WAV:
                await stream_wav(ws, WAV, RATE)
                await ws.send(json.dumps({"type": "stop"}))
            else:
                await stream_mic(ws, RATE)

        async def receiver():
            async for msg in ws:
                try:
                    obj = json.loads(msg)
                    if "text" in obj:
                        print(f"📝 Transcript: {obj['text']}")
                        if obj.get("final"):
                            print("✅ Final transcript received.")
                            break
                    else:
                        print("STT:", obj)
                except Exception:
                    print("STT raw:", msg)

        await asyncio.gather(sender(), receiver())

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n⏹️  Stopped.")
