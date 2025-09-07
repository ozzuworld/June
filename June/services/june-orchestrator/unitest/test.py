# unitest/test.py
import os, sys, argparse, json, base64, requests

def require(name, value):
    if not value:
        print(f"Missing env/flag: {name}", file=sys.stderr); sys.exit(2)
    return value

def get_id_token(api_key: str, email: str, password: str) -> dict:
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    r = requests.post(url, json=payload, timeout=30)
    try: r.raise_for_status()
    except requests.HTTPError: print("Firebase sign-in failed:", r.text, file=sys.stderr); raise
    return r.json()

def decode_jwt(jwt: str):
    try:
        h,p,_ = jwt.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        b64d = lambda s: json.loads(base64.urlsafe_b64decode(pad(s)).decode())
        return b64d(h), b64d(p)
    except Exception: return None, None

def call(method, url, headers=None, json_body=None, timeout=60):
    print(f"\n=== {method} {url}")
    if headers: print("Headers:", {k: (v[:30]+"...(redacted)" if k.lower()=="authorization" else v) for k,v in headers.items()})
    if json_body is not None: print("Body:", json_body)
    resp = requests.request(method, url, headers=headers or {}, json=json_body, timeout=timeout)
    print("Status:", resp.status_code)
    try: print("JSON:", json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception: print("Text:", resp.text)
    return resp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("BASE_URL", "https://june-orchestrator-359243954.us-central1.run.app"))
    ap.add_argument("--api-key", default=os.getenv("FIREBASE_API_KEY"))
    ap.add_argument("--email",   default=os.getenv("FIREBASE_TEST_EMAIL"))
    ap.add_argument("--password",default=os.getenv("FIREBASE_TEST_PASSWORD"))
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    api_key  = require("FIREBASE_API_KEY/--api-key", args.api_key)
    email    = require("FIREBASE_TEST_EMAIL/--email", args.email)
    password = require("FIREBASE_TEST_PASSWORD/--password", args.password)

    # 0) Health
    call("GET", f"{base}/healthz")

    # 1) Sign in
    auth = get_id_token(api_key, email, password)
    id_token = auth["idToken"]
    h,p = decode_jwt(id_token)
    print("\n== TOKEN ==")
    print("len:", len(id_token))
    print("header:", h)
    # redact some payload fields
    if p:
        p = {**p}
        for k in ("email","user_id","sub"): 
            if k in p: p[k] = str(p[k])[:4]+"...(redacted)"
    print("payload:", p)

    # 2) whoami (proves the server sees your claims)
    headers = {"Authorization": f"Bearer {id_token}"}
    call("GET", f"{base}/whoami", headers=headers)

    # 3) chat
    body = {"user_input": "Hello June, do you have multimodal capabilities like computer vision?"}
    resp = call("POST", f"{base}/v1/chat", headers={**headers, "Content-Type": "application/json"}, json_body=body)

    assert resp.status_code == 200, f"Expected 200 for GOOD TOKEN, got {resp.status_code}"

if __name__ == "__main__":
    main()
