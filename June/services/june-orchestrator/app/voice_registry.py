#!/usr/bin/env python3
"""
Voice Registry for CosyVoice2

CosyVoice2 does NOT support predefined speaker IDs like CosyVoice v1.
Instead, it uses:
- Language codes for synthesis
- Reference audio for voice cloning (zero-shot)
- Language tags for cross-lingual synthesis

OLD (CosyVoice v1 - NOT SUPPORTED):
  speaker_id = "英文女"  # English Female
  
NEW (CosyVoice2):
  language = "en"  # English
  # Voice characteristics come from reference audio
"""
from typing import Dict, List

# Supported languages in CosyVoice2
SUPPORTED_LANGUAGES = {
    "en": "English",
    "zh": "Chinese (Mandarin)",
    "jp": "Japanese",
    "ko": "Korean",
    "yue": "Cantonese",
}

DEFAULT_LANGUAGE = "en"


def get_language_code(language: str = "en") -> str:
    """Get validated language code
    
    Args:
        language: Language code (en, zh, jp, ko, yue)
        
    Returns:
        Validated language code, defaults to 'en' if invalid
    """
    if language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def get_default_language() -> str:
    """Get default language"""
    return DEFAULT_LANGUAGE


def list_available_languages() -> Dict[str, str]:
    """List all supported languages
    
    Returns:
        Dictionary mapping language codes to names
    """
    return SUPPORTED_LANGUAGES.copy()


def get_language_name(language_code: str) -> str:
    """Get human-readable name for language code
    
    Args:
        language_code: Language code (en, zh, etc.)
        
    Returns:
        Language name or 'Unknown'
    """
    return SUPPORTED_LANGUAGES.get(language_code, "Unknown")


# Legacy compatibility - maps old speaker IDs to language codes
# This helps transition from v1 to v2 if any old code references speakers
LEGACY_SPEAKER_TO_LANGUAGE = {
    "英文女": "en",  # English Female -> en
    "英文男": "en",  # English Male -> en
    "中文女": "zh",  # Chinese Female -> zh
    "中文男": "zh",  # Chinese Male -> zh
    "日语男": "jp",  # Japanese Male -> jp
    "粤语女": "yue", # Cantonese Female -> yue
    "韩语女": "ko",  # Korean Female -> ko
}


def convert_legacy_speaker_to_language(speaker_id: str) -> str:
    """Convert old CosyVoice v1 speaker ID to language code
    
    This is for backward compatibility only.
    
    Args:
        speaker_id: Old speaker ID like "英文女"
        
    Returns:
        Language code (en, zh, etc.)
    """
    return LEGACY_SPEAKER_TO_LANGUAGE.get(speaker_id, DEFAULT_LANGUAGE)


__all__ = [
    "SUPPORTED_LANGUAGES",
    "get_language_code",
    "get_default_language",
    "list_available_languages",
    "get_language_name",
    "convert_legacy_speaker_to_language",
]
