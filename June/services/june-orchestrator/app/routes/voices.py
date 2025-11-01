#!/usr/bin/env python3
"""
Voice management endpoints for Chatterbox TTS integration
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
import httpx

from ..config import config
from ..voice_registry import VOICE_REGISTRY, get_available_voices, resolve_voice_reference

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/voices")
async def list_available_voices():
    """
    Get list of available voices in the registry.
    """
    voices = get_available_voices()
    
    return {
        "status": "success",
        "voices": voices,
        "count": len(voices),
        "default_voice": resolve_voice_reference(None, None)
    }


@router.post("/api/voices/warmup")
async def warmup_voice(voice_id: str = Query(..., description="Voice ID from registry to warmup")):
    """
    Pre-warm a voice in the TTS service to cache embeddings.
    This reduces latency for the first synthesis with this voice.
    """
    if voice_id not in VOICE_REGISTRY:
        raise HTTPException(
            status_code=404, 
            detail=f"Unknown voice_id '{voice_id}'. Available: {list(VOICE_REGISTRY.keys())}"
        )
    
    reference_url = VOICE_REGISTRY[voice_id]
    
    # Trigger a short synthesis to cache the voice embeddings
    payload = {
        "text": "Warmup.",
        "language": "en",
        "speaker_wav": [reference_url],
        "exaggeration": 0.5,
        "cfg_weight": 0.8
    }
    
    try:
        tts_url = f"{config.services.tts_base_url}/synthesize"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(tts_url, json=payload)
            
            if response.status_code != 200:
                logger.error(f"❌ Voice warmup failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=502, 
                    detail=f"TTS service error: {response.status_code}"
                )
            
            logger.info(f"✅ Voice '{voice_id}' warmed up successfully")
            
            return {
                "status": "success",
                "voice_id": voice_id,
                "reference_url": reference_url,
                "message": f"Voice '{voice_id}' embeddings cached in TTS service"
            }
            
    except httpx.TimeoutException:
        logger.error(f"❌ Voice warmup timeout for '{voice_id}'")
        raise HTTPException(status_code=504, detail="TTS service timeout")
    except Exception as e:
        logger.error(f"❌ Voice warmup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/voices/resolve")
async def resolve_voice(speaker: str = None, speaker_wav: str = None):
    """
    Test voice resolution logic.
    Shows what reference URL would be used for given speaker/speaker_wav.
    """
    resolved_reference = resolve_voice_reference(speaker, speaker_wav)
    
    return {
        "status": "success",
        "input": {
            "speaker": speaker,
            "speaker_wav": speaker_wav
        },
        "resolved_reference": resolved_reference,
        "resolution_method": (
            "direct_speaker_wav" if speaker_wav 
            else "registry_lookup" if speaker and speaker in VOICE_REGISTRY 
            else "default_fallback"
        )
    }
