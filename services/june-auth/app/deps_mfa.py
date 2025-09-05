import os, time, secrets, base64
import pyotp
from jose import jwt
from cryptography.fernet import Fernet
from passlib.hash import bcrypt
from google.cloud import firestore

FERNET = Fernet(os.environ["FERNET_KEY"].encode())
DB = firestore.Client()  # Use default project from metadata; no hard env dependency

ISSUER = os.getenv("TOTP_ISSUER", "June Voice")
ALG = os.getenv("TOTP_ALG", "SHA1")
DIGITS = int(os.getenv("TOTP_DIGITS", "6"))
PERIOD = int(os.getenv("TOTP_PERIOD", "30"))
MFA_SECRET = os.environ["MFA_JWT_SECRET"]
MFA_TTL = int(os.getenv("MFA_JWT_TTL_SECONDS", "600"))

def totp_doc(uid):
    return DB.collection("users").document(uid).collection("mfa").document("totp")

def gen_secret():
    return pyotp.random_base32()

def enc(b32_secret: str) -> str:
    return FERNET.encrypt(b32_secret.encode()).decode()

def dec(ct: str) -> str:
    return FERNET.decrypt(ct.encode()).decode()

def build_totp(b32: str) -> pyotp.TOTP:
    return pyotp.TOTP(b32, digits=DIGITS, interval=PERIOD, digest=ALG.lower())

def create_recovery_codes(n=10):
    return [secrets.token_hex(5) for _ in range(n)]

def hash_codes(codes):
    return [bcrypt.hash(c) for c in codes]

def verify_code_against_hashes(code, hashed_list):
    return any(bcrypt.verify(code, h) for h in hashed_list)

def mint_mfa_jwt(uid: str, scopes=None):
    now = int(time.time())
    payload = {"sub": uid, "typ": "mfa", "iat": now, "exp": now + MFA_TTL, "scopes": scopes or ["ws","orchestrator"]}
    return jwt.encode(payload, MFA_SECRET, algorithm="HS256")

def verify_mfa_jwt(token: str) -> dict:
    return jwt.decode(token, MFA_SECRET, algorithms=["HS256"])
