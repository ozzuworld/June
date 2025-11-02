"""Pydantic models for the June Orchestrator"""

# Domain models
from .domain import (
    Message,
    Session,
    SessionStats,
    SkillSession,
    UtteranceState
)

# Request/Response models
from .requests import (
    STTWebhookPayload,
    TTSPublishRequest,
    SessionCreateRequest,
    MessageAddRequest
)

from .responses import (
    WebhookResponse,
    SessionResponse,
    StreamingStatus
)

# Legacy models from original models.py (for backward compatibility)
from .legacy import (
    SessionCreate,
    LiveKitWebhook,
    GuestTokenRequest,
    GuestTokenResponse,
    AIRequest,
    AIResponse
)

__all__ = [
    # Domain models
    "Message",
    "Session", 
    "SessionStats",
    "SkillSession",
    "UtteranceState",
    # Request models
    "STTWebhookPayload",
    "TTSPublishRequest",
    "SessionCreateRequest",
    "MessageAddRequest",
    # Response models
    "WebhookResponse",
    "SessionResponse",
    "StreamingStatus",
    # Legacy models (backward compatibility)
    "SessionCreate",
    "LiveKitWebhook",
    "GuestTokenRequest",
    "GuestTokenResponse",
    "AIRequest",
    "AIResponse"
]