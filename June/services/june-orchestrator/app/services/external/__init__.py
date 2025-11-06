"""External service clients - Cleaned up

REMOVED:
- TTSClient (old implementation, use tts_service.py instead)

KEPT:
- LiveKitClient
- STTClient
"""

from .livekit import LiveKitClient
from .stt import STTClient

__all__ = [
    "LiveKitClient",
    "STTClient"
]