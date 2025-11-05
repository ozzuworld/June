"""Health check routes"""
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/readyz")
async def readiness_check():
    return {
        "status": "ready",
        "service": "june-orchestrator",
        "version": "2.0.0"
    }