#!/usr/bin/env python3
"""
Voice Registry for CosyVoice2 Integration
Maps speaker IDs to CosyVoice2 modes and configurations.
"""
import os
from typing import Optional, Dict

# CosyVoice2 Default Speakers (SFT Mode)
# These are built-in speakers in the CosyVoice2-0.5B model
COSYVOICE2_SPEAKERS = {
    # Chinese
    "zh_female": "中文女",
    "zh_male": "中文男",
    
    # English  
    "en_female": "英文女",
    "en_male": "英文男",
    
    # Japanese
    "jp_male": "日语男",
    
    # Cantonese
    "yue_female": "粤语女",
    
    # Korean
    "ko_female": "韩语女",
}

# Default voice configuration
DEFAULT_VOICE_ID = os.getenv("DEFAULT_VOICE_ID", "en_female")


def get_speaker_id(language: str = "en", gender: str = "female") -> str:
    """
    Get CosyVoice2 speaker ID for language and gender
    
    Args:
        language: Language code (en, zh, jp, ko, yue)
        gender: Gender (male, female)
        
    Returns:
        CosyVoice2 speaker ID (e.g., "中文女")
    """
    key = f"{language}_{gender}"
    
    if key in COSYVOICE2_SPEAKERS:
        return COSYVOICE2_SPEAKERS[key]
    
    # Fallback to default
    return COSYVOICE2_SPEAKERS[DEFAULT_VOICE_ID]


def get_default_speaker() -> str:
    """Get default CosyVoice2 speaker"""
    return COSYVOICE2_SPEAKERS[DEFAULT_VOICE_ID]


def list_available_speakers() -> Dict[str, str]:
    """Get all available CosyVoice2 speakers"""
    return COSYVOICE2_SPEAKERS.copy()


def validate_speaker_id(speaker_id: str) -> bool:
    """
    Validate if speaker ID is a valid CosyVoice2 speaker
    
    Args:
        speaker_id: Speaker ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    return speaker_id in COSYVOICE2_SPEAKERS.values()


def get_language_from_speaker(speaker_id: str) -> Optional[str]:
    """
    Extract language code from speaker ID
    
    Args:
        speaker_id: CosyVoice2 speaker ID
        
    Returns:
        Language code or None
    """
    speaker_language_map = {
        "中文女": "zh",
        "中文男": "zh",
        "英文女": "en",
        "英文男": "en",
        "日语男": "jp",
        "粤语女": "yue",
        "韩语女": "ko",
    }
    
    return speaker_language_map.get(speaker_id)


# Backward compatibility aliases (for migration from old system)
# These will be deprecated in future versions
LEGACY_SPEAKER_MAPPING = {
    "Alexandra Hisakawa": "en_female",
    "assistant_neutral": "en_female",
    "neutral_male": "en_male",
    "neutral_female": "en_female",
}


def resolve_legacy_speaker(legacy_name: Optional[str]) -> str:
    """
    Resolve legacy speaker names to CosyVoice2 speaker IDs
    
    Args:
        legacy_name: Old speaker name from previous TTS system
        
    Returns:
        CosyVoice2 speaker ID
    """
    if not legacy_name:
        return get_default_speaker()
    
    # Check if it's already a valid CosyVoice2 speaker
    if validate_speaker_id(legacy_name):
        return legacy_name
    
    # Map from legacy system
    if legacy_name in LEGACY_SPEAKER_MAPPING:
        mapped_key = LEGACY_SPEAKER_MAPPING[legacy_name]
        return COSYVOICE2_SPEAKERS[mapped_key]
    
    # Default fallback
    return get_default_speaker()


# Export public API
__all__ = [
    "COSYVOICE2_SPEAKERS",
    "get_speaker_id",
    "get_default_speaker",
    "list_available_speakers",
    "validate_speaker_id",
    "get_language_from_speaker",
    "resolve_legacy_speaker",
]