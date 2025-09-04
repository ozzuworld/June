# unitest/tts_test.py
import os, sys, argparse, requests, base64
from dotenv import load_dotenv

load_dotenv()

def require(name, val):
    if not val:
        print(f"Missing {name}", file=sys.stderr)
        sys.exit(2)
    return val

def get_firebase_id_token(api_key: str, email: str, password: str) -> str:
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["idToken"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("TTS_BASE", "https://june-tts-359243954.us-central1.run.app"))
    ap.add_argument("--path", default=os.getenv("TTS_PATH", "/v1/tts"))
    ap.add_argument("--text", default="Hello June, this is a test of TTS.")
    ap.add_argument("--api-key", default=os.getenv("FIREBASE_API_KEY"))
    ap.add_argument("--email",   default=os.getenv("FIREBASE_TEST_EMAIL"))
    ap.add_argument("--password",default=os.getenv("FIREBASE_TEST_PASSWORD"))
    ap.add_argument("--outfile", default="tts_output.wav")
    args = ap.parse_args()

    api_key  = require("FIREBASE_API_KEY", args.api_key)
    email    = require("FIREBASE_TEST_EMAIL", args.email)
    password = require("FIREBASE_TEST_PASSWORD", args.password)

    id_token = get_firebase_id_token(api_key, email, password)

    base = args.base.rstrip("/")
    path = args.path if args.path.startswith("/") else "/" + args.path
    url = f"{base}{path}"

    headers = {"Authorization": f"Bearer {id_token}"}
    full_url = f"{url}?text={args.text}"

    print(f"POST {full_url}")
    r = requests.post(full_url, headers=headers, timeout=60)

    if r.status_code != 200:
        print("Error:", r.status_code, r.text)
        return

    ctype = r.headers.get("content-type", "")
    outfile = args.outfile

    if "application/json" in ctype:
        # JSON response with base64 audio
        resp = r.json()
        audio_b64 = resp.get("audioContent") or resp.get("audio")
        if not audio_b64:
            print("Response JSON missing audio content:", resp)
            return
        audio_bytes = base64.b64decode(audio_b64)
    else:
        # Raw audio (e.g. audio/wav or audio/mpeg)
        audio_bytes = r.content

    with open(outfile, "wb") as f:
        f.write(audio_bytes)

    print(f"✅ TTS audio saved to {outfile} ({len(audio_bytes)} bytes)")

if __name__ == "__main__":
    main()
