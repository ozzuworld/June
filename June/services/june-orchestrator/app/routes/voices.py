#!/usr/bin/env python3
"""
Voice management endpoints for CosyVoice2 integration

CosyVoice2 uses language codes (en, zh, jp, ko, yue) instead of predefined speaker IDs.
Voice characteristics come from reference audio, not speaker embeddings.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any

from ..config import config
from ..voice_registry import (
    SUPPORTED_LANGUAGES,
    get_language_code,
    get_default_language,
    list_available_languages,
    get_language_name,
    convert_legacy_speaker_to_language
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/voices")
async def list_available_voices():
    """
    Get list of available languages for CosyVoice2.
    
    Note: CosyVoice2 does NOT use predefined speaker IDs.
    Voice characteristics come from reference audio.
    """
    languages = list_available_languages()
    
    return {
        "status": "success",
        "engine": "cosyvoice2",
        "model": "CosyVoice2-0.5B",
        "note": "CosyVoice2 uses language codes, not speaker IDs. Voice cloning uses reference audio.",
        "languages": languages,
        "count": len(languages),
        "default_language": get_default_language(),
        "synthesis_methods": ["zero_shot", "cross_lingual", "instruct2"]
    }


@router.get("/api/voices/{language}")
async def get_voice_by_language(language: str):
    """
    Get information about a specific language.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{language}' not supported. Available: {', '.join(SUPPORTED_LANGUAGES.keys())}"
        )
    
    return {
        "status": "success",
        "language_code": language,
        "language_name": get_language_name(language),
        "synthesis_method": "zero_shot with reference audio",
        "note": "Voice characteristics come from reference audio, not predefined speakers"
    }


@router.post("/api/voices/resolve")
async def resolve_voice(speaker: str = None, language: str = "en"):
    """
    Resolve voice parameters to language code.
    Supports legacy speaker names for backward compatibility.
    
    Args:
        speaker: Legacy speaker ID (e.g., "英文女") - will be converted to language code
        language: Target language code (en, zh, jp, ko, yue)
    """
    
    # Try to resolve legacy speaker name (for backward compatibility)
    if speaker:
        resolved_language = convert_legacy_speaker_to_language(speaker)
        return {
            "status": "success",
            "input": {"speaker": speaker},
            "resolved_language": resolved_language,
            "language_name": get_language_name(resolved_language),
            "method": "legacy_speaker_to_language_conversion",
            "note": "CosyVoice2 uses language codes. Speaker IDs are converted for compatibility."
        }
    
    # Validate and return language code
    validated_language = get_language_code(language)
    
    return {
        "status": "success",
        "input": {"language": language},
        "resolved_language": validated_language,
        "language_name": get_language_name(validated_language),
        "method": "language_code_validation"
    }


@router.get("/api/voices/info")
async def get_voice_info():
    """
    Get information about CosyVoice2 voice synthesis system.
    """
    return {
        "status": "success",
        "engine": "CosyVoice2-0.5B",
        "version": "2.0",
        "architecture": "LLM-based streaming TTS",
        "features": {
            "zero_shot": "Voice cloning from short reference audio (3-10s)",
            "cross_lingual": "Multilingual synthesis with language tags",
            "instruct2": "Natural language control of speech characteristics",
            "streaming": "Real-time audio streaming with <200ms latency",
            "multilingual": True
        },
        "supported_languages": SUPPORTED_LANGUAGES,
        "total_languages": len(SUPPORTED_LANGUAGES),
        "default_language": get_default_language(),
        "sample_rate": "22050 Hz",
        "typical_latency_ms": {
            "zero_shot_synthesis": "150-300ms",
            "first_audio_packet": "<200ms"
        },
        "note": "CosyVoice2 does NOT support SFT mode or predefined speaker IDs. Use zero-shot with reference audio."
    }


@router.get("/api/voices/legacy-mapping")
async def get_legacy_mapping():
    """
    Get mapping of legacy speaker IDs to language codes.
    Useful for migrating from CosyVoice v1 to v2.
    """
    from ..voice_registry import LEGACY_SPEAKER_TO_LANGUAGE
    
    return {
        "status": "success",
        "note": "Legacy speaker IDs from CosyVoice v1 are automatically converted to language codes",
        "mapping": LEGACY_SPEAKER_TO_LANGUAGE,
        "supported_languages": SUPPORTED_LANGUAGES
    }
