"""External service clients - XTTS-focused only.

We deliberately only expose LiveKitClient here.

The old STTClient was unused by the live XTTS / webhook paths, and the
STT module has been removed. Importing it here would break app startup
if the file is missing, even if nothing actually uses STTClient.
"""

from .livekit import LiveKitClient

__all__ = [
    "LiveKitClient",
]
