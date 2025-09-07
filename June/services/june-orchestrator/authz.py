# authz.py — shared by all three services
from typing import Optional
from fastapi import Header, HTTPException
from starlette.websockets import WebSocket
import os

# Firebase Admin
import firebase_admin
from firebase_admin import auth as fb_auth, credentials

if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'projectId': os.getenv('FIREBASE_PROJECT_ID')
    })

class User:
    def __init__(self, uid: str, email: Optional[str]):
        self.uid = uid
        self.email = email

# HTTP dependency
async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        decoded = fb_auth.verify_id_token(token)
        return User(decoded.get('uid'), decoded.get('email'))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid ID token")

# WS query helper used by STT/Orchestrator
async def verify_token_query(ws: WebSocket, token: Optional[str]) -> User:
    if not token:
        await ws.close(code=4401)
        raise RuntimeError("Missing token")
    try:
        decoded = fb_auth.verify_id_token(token)
        return User(decoded.get('uid'), decoded.get('email'))
    except Exception:
        await ws.close(code=4401)
        raise
