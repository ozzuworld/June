from fastapi import APIRouter
import time
import os

router = APIRouter(tags=["admin"])

@router.get("/healthz")
def healthz():
    """Health check endpoint"""
    return {
        "status": "ok", 
        "service": "june-tts",
        "timestamp": time.time(),
        "engine": "MeloTTS",
        "voice_cloning": "basic"
    }

@router.get("/voices")
def voices():
    """Get available voices"""
    return {
        "env": {
            "MELO_SPEAKER_ID": os.getenv("MELO_SPEAKER_ID", "0"),
            "MELO_LANGUAGE": os.getenv("MELO_LANGUAGE", "EN"),
        },
        "voices": {
            "0": "Default Voice",
            "1": "Alternative Voice"
        },
        "note": "Basic MeloTTS voices available"
    }
