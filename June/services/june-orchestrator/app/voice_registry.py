#!/usr/bin/env python3
"""
Simplified Voice Registry for CosyVoice2
Maps languages to speaker IDs - that's it!
"""
from typing import Dict, Optional

# CosyVoice2 speakers (maintained by june-tts)
COSYVOICE2_SPEAKERS = {
    "zh_female": "中文女",
    "zh_male": "中文男",
    "en_female": "英文女",
    "en_male": "英文男",
    "jp_male": "日语男",
    "yue_female": "粤语女",
    "ko_female": "韩语女",
}

DEFAULT_SPEAKER = "en_female"


def get_speaker_id(language: str = "en", gender: str = "female") -> str:
    """Get speaker ID for language/gender"""
    key = f"{language}_{gender}"
    return COSYVOICE2_SPEAKERS.get(key, COSYVOICE2_SPEAKERS[DEFAULT_SPEAKER])


def get_default_speaker() -> str:
    """Get default speaker"""
    return COSYVOICE2_SPEAKERS[DEFAULT_SPEAKER]


def list_available_speakers() -> Dict[str, str]:
    """List all speakers"""
    return COSYVOICE2_SPEAKERS.copy()


__all__ = [
    "COSYVOICE2_SPEAKERS",
    "get_speaker_id",
    "get_default_speaker",
    "list_available_speakers",
]
