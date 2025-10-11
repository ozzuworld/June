"""Voice routes"""
from fastapi import APIRouter
voice_bp = APIRouter()

@voice_bp.get("/health")
async def voice_health():
    return {"status": "ok", "service": "voice"}