# Real-Time Conversation Engine - SOTA Natural Flow Implementation
# Based on 2024-2025 voice AI research: sub-1.5s latency, phrase streaming, full-duplex

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List, Callable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from collections import deque
import json

from ..core.dependencies import get_redis_client  # USE SHARED REDIS CLIENT

logger = logging.getLogger(__name__)

@dataclass
class ConversationState:
    """Real-time conversation state tracking"""
    session_id: str
    is_ai_speaking: bool = False
    is_user_speaking: bool = False
    last_user_input_time: Optional[datetime] = None
    last_ai_response_time: Optional[datetime] = None
    current_ai_task: Optional[asyncio.Task] = None
    pending_interruption: bool = False
    conversation_complexity: str = "simple"  # simple, medium, complex
    turn_count: int = 0

class RealTimeConversationEngine:
    """SOTA conversation engine achieving <1.5s latency with natural turn-taking"""
    
    def __init__(self, redis_client=None, tts_service=None, streaming_ai_service=None):
        # Use the shared Redis client from DI if not provided
        self.redis = redis_client or get_redis_client()
        self.tts = tts_service
        self.streaming_ai = streaming_ai_service
        self.active_conversations: Dict[str, ConversationState] = {}
        
        # SOTA timing thresholds (based on 2024-2025 research)
        self.SIMPLE_RESPONSE_MAX_MS = 200
        self.NORMAL_RESPONSE_MAX_MS = 800
        self.PHRASE_MIN_TOKENS = 4
        self.TOKEN_GAP_THRESHOLD_MS = 80
        self.INTERRUPTION_DETECT_MS = 200
        self.TURN_TAKING_PAUSE_MS = 150
        
        self.hesitation_patterns = {
            "processing": ["Hmm,", "Let me think,", "Well,"],
            "complex": ["That's a great question.", "Interesting point."],
            "simple": []
        }
    
    # ... rest of file unchanged ...
