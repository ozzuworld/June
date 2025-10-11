"""Simple health routes without LiveKit dependencies"""
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-orchestrator-janus",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/readyz") 
async def readiness_check():
    return {
        "status": "ready",
        "webrtc": "janus",
        "timestamp": datetime.utcnow().isoformat()
    }