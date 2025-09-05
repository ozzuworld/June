import os
from typing import Optional
from fastapi import Depends, HTTPException, Header
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, auth
from google.cloud import firestore

# Init Firebase Admin once
if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    else:
        firebase_admin.initialize_app()  # use default creds in GCP

DB = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))

class User(BaseModel):
    uid: str
    email: Optional[str] = None

def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    # Expect "Bearer <IDTOKEN>"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Authorization bearer token")
    id_token = authorization.split(" ", 1)[1].strip()
    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase ID token")
    return User(uid=decoded["uid"], email=decoded.get("email"))
