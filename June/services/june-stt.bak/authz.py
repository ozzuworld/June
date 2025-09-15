# june-stt/authz.py
from typing import Optional
import os, logging

import firebase_admin
from firebase_admin import auth as fb_auth
from fastapi import Header, HTTPException

logger = logging.getLogger("uvicorn.error")

_FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
if _FIREBASE_PROJECT_ID:
    firebase_admin.initialize_app(options={"projectId": _FIREBASE_PROJECT_ID})
    logger.info(f"[authz] Firebase Admin initialized with explicit projectId={_FIREBASE_PROJECT_ID}")
else:
    firebase_admin.initialize_app()
    logger.info("[authz] Firebase Admin initialized with ADC project")

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = fb_auth.verify_id_token(token)
        logger.info(f"[auth] ok uid={claims.get('uid')} email={claims.get('email')}")
        return claims
    except Exception:
        logger.exception("[auth] verify_id_token failed")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def verify_token_query(token: Optional[str]):
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        claims = fb_auth.verify_id_token(token)
        logger.info(f"[auth-ws] ok uid={claims.get('uid')} email={claims.get('email')}")
        return claims
    except Exception:
        logger.exception("[auth-ws] verify_id_token failed")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
