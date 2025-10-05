"""
Pydantic data models for the June TTS API responses.

These classes can be used for response modelling and OpenAPI documentation.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any


class VoiceInfo(BaseModel):
    id: str
    display_name: str
    language: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class VoiceList(BaseModel):
    voices: List[VoiceInfo]