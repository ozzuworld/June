#!/usr/bin/env python3
"""
Voice Registry for Chatterbox TTS Integration
Maps speaker names to reference audio URLs for voice cloning.
"""
import os
from typing import Optional

# Default voice configuration
DEFAULT_VOICE_ID = os.getenv("DEFAULT_VOICE_ID", "assistant_neutral")

# Voice registry mapping speaker names to reference audio URLs
# Can be overridden via environment variables
VOICE_REGISTRY = {
    # Backward compatibility with existing XTTS speakers
    "Alexandra Hisakawa": os.getenv(
        "VOICE_ALEXANDRA", 
        "https://assets.ozzu.world/voices/alexandra.wav"
    ),
    
    # New default voices for Chatterbox
    "assistant_neutral": os.getenv(
        "VOICE_ASSISTANT_NEUTRAL", 
        "https://assets.ozzu.world/voices/assistant_neutral.wav"
    ),
    "neutral_male": os.getenv(
        "VOICE_NEUTRAL_MALE", 
        "https://assets.ozzu.world/voices/neutral_male.wav"
    ),
    "neutral_female": os.getenv(
        "VOICE_NEUTRAL_FEMALE", 
        "https://assets.ozzu.world/voices/neutral_female.wav"
    ),
    
    # Additional voices can be added here
    "professional_male": os.getenv(
        "VOICE_PROFESSIONAL_MALE", 
        "https://assets.ozzu.world/voices/professional_male.wav"
    ),
    "professional_female": os.getenv(
        "VOICE_PROFESSIONAL_FEMALE", 
        "https://assets.ozzu.world/voices/professional_female.wav"
    ),
}


def resolve_voice_reference(speaker: Optional[str], speaker_wav: Optional[str]) -> str:
    """
    Resolve speaker name to voice reference URL.
    
    Priority:
    1. If speaker_wav is provided, use it directly
    2. If speaker is in registry, use mapped URL
    3. Fall back to default voice
    
    Args:
        speaker: Human-friendly speaker name (e.g., "Alexandra Hisakawa")
        speaker_wav: Direct reference audio URL/path
        
    Returns:
        str: Reference audio URL for Chatterbox TTS
    """
    # Prefer provided speaker_wav
    if speaker_wav and speaker_wav.strip():
        return speaker_wav.strip()
    
    # Map speaker name to registry
    if speaker and speaker in VOICE_REGISTRY:
        return VOICE_REGISTRY[speaker]
    
    # Default fallback
    return VOICE_REGISTRY[DEFAULT_VOICE_ID]


def get_available_voices() -> dict:
    """
    Get list of available voices in the registry.
    
    Returns:
        dict: Mapping of voice IDs to reference URLs
    """
    return VOICE_REGISTRY.copy()


def validate_voice_reference(reference: str) -> bool:
    """
    Basic validation for voice reference URLs.
    
    Args:
        reference: Voice reference URL or path
        
    Returns:
        bool: True if reference appears valid
    """
    if not reference or not reference.strip():
        return False
    
    # Basic URL/path validation
    reference = reference.strip()
    
    # Allow HTTP/HTTPS URLs
    if reference.startswith(("http://", "https://")):
        return True
    
    # Allow absolute paths (for local files)
    if reference.startswith("/"):
        return True
    
    # Reject relative paths for security
    return False
