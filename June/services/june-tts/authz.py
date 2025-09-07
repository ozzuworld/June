# authz.py
import firebase_admin
from firebase_admin import auth as fb_auth
from fastapi import Header, HTTPException
from typing import Optional

# Initializes once on first import (works on Cloud Run with ADC)
default_app = firebase_admin.initialize_app()

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        return fb_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def verify_token_query(token: Optional[str]):
    """
    Verify Firebase ID token coming from a query param (e.g., for WebSocket ?token=...).
    Raises HTTPException(401) on failure. Returns claims dict on success.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        return fb_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
