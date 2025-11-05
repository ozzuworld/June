#!/usr/bin/env python3
"""
Voice management endpoints for CosyVoice2 integration
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any

from ..config import config
from ..voice_registry import (
    COSYVOICE2_SPEAKERS,
    get_speaker_id,
    get_default_speaker,
    list_available_speakers,
    resolve_legacy_speaker
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/voices")
async def list_available_voices():
    """
    Get list of available CosyVoice2 speakers.
    """
    speakers = list_available_speakers()
    
    return {
        "status": "success",
        "engine": "cosyvoice2",
        "speakers": speakers,
        "count": len(speakers),
        "default_speaker": get_default_speaker(),
        "available_languages": ["en", "zh", "jp", "ko", "yue"]
    }


@router.get("/api/voices/{language}")
async def get_voices_by_language(language: str):
    """
    Get available speakers for a specific language.
    """
    speakers = {}
    
    if language == "en":
        speakers = {
            "en_female": COSYVOICE2_SPEAKERS["en_female"],
            "en_male": COSYVOICE2_SPEAKERS["en_male"]
        }
    elif language == "zh":
        speakers = {
            "zh_female": COSYVOICE2_SPEAKERS["zh_female"],
            "zh_male": COSYVOICE2_SPEAKERS["zh_male"]
        }
    elif language == "jp":
        speakers = {
            "jp_male": COSYVOICE2_SPEAKERS["jp_male"]
        }
    elif language == "ko":
        speakers = {
            "ko_female": COSYVOICE2_SPEAKERS["ko_female"]
        }
    elif language == "yue":
        speakers = {
            "yue_female": COSYVOICE2_SPEAKERS["yue_female"]
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{language}' not supported. Available: en, zh, jp, ko, yue"
        )
    
    return {
        "status": "success",
        "language": language,
        "speakers": speakers,
        "count": len(speakers)
    }


@router.post("/api/voices/resolve")
async def resolve_voice(speaker: str = None, language: str = "en", gender: str = "female"):
    """
    Resolve speaker name to CosyVoice2 speaker ID.
    Supports legacy speaker names for backward compatibility.
    """
    
    # Try to resolve legacy speaker name
    if speaker:
        resolved = resolve_legacy_speaker(speaker)
        return {
            "status": "success",
            "input": {"speaker": speaker},
            "resolved_speaker_id": resolved,
            "method": "legacy_mapping" if speaker != resolved else "direct"
        }
    
    # Get speaker by language and gender
    speaker_id = get_speaker_id(language, gender)
    
    return {
        "status": "success",
        "input": {
            "language": language,
            "gender": gender
        },
        "resolved_speaker_id": speaker_id,
        "method": "language_gender_mapping"
    }


@router.get("/api/voices/info")
async def get_voice_info():
    """
    Get information about CosyVoice2 voice system.
    """
    return {
        "status": "success",
        "engine": "CosyVoice2-0.5B",
        "version": "2.0",
        "features": {
            "sft_mode": "Predefined speakers (fastest, most stable)",
            "zero_shot_mode": "Voice cloning from reference audio",
            "instruct_mode": "Natural language control",
            "streaming": "Real-time audio streaming",
            "multilingual": True,
            "cross_lingual": True
        },
        "supported_languages": {
            "en": "English",
            "zh": "Chinese (Mandarin)",
            "jp": "Japanese",
            "ko": "Korean",
            "yue": "Cantonese"
        },
        "total_speakers": len(COSYVOICE2_SPEAKERS),
        "default_speaker": get_default_speaker(),
        "sample_rate": "22050 Hz",
        "latency": "~150ms (first packet)"
    }