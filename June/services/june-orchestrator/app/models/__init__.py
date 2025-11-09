"""Pydantic models for the June Orchestrator (XTTS-focused runtime set).

This only exposes the models that are actually used by the live routes:
- Domain models (sessions/messages)
- Request models for webhooks / TTS
- Response models for webhooks / streaming status

Legacy models (SessionCreate, AIRequest, etc.) are intentionally NOT imported
here so that the legacy module can be removed without breaking imports.
"""

# Domain models
from .domain import (
    Message,
    Session,
    SessionStats,
    SkillSession,
    UtteranceState,
)

# Request models
from .requests import (
    STTWebhookPayload,
    TTSPublishRequest,
    SessionCreateRequest,
    MessageAddRequest,
)

# Response models
from .responses import (
    WebhookResponse,
    SessionResponse,
    StreamingStatus,
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
]
