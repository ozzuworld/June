"""Utterance state management for June STT"""
import uuid
import logging
from datetime import datetime
from typing import Dict, Optional, Deque
from collections import deque
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class UtteranceState:
    """State tracking for individual utterances"""
    buffer: Deque[np.ndarray] = None
    is_active: bool = False
    started_at: Optional[datetime] = None
    last_audio_at: Optional[datetime] = None
    total_samples: int = 0
    first_partial_sent: bool = False
    last_partial_sent_at: Optional[datetime] = None
    partial_sequence: int = 0
    utterance_id: str = ""
    ultra_fast_triggered: bool = False
    sota_optimization_used: bool = False
    
    def __post_init__(self):
        if self.buffer is None:
            self.buffer = deque()
        if not self.utterance_id:
            self.utterance_id = str(uuid.uuid4())


class UtteranceManager:
    """Manages utterance states for all participants"""
    
    def __init__(self):
        self.utterance_states: Dict[str, UtteranceState] = {}
        
    def ensure_utterance_state(self, participant_id: str) -> UtteranceState:
        """Ensure utterance state exists for participant"""
        if participant_id not in self.utterance_states:
            self.utterance_states[participant_id] = UtteranceState()
            logger.debug(f"🚀 SOTA: Created new utterance state for {participant_id}")
        return self.utterance_states[participant_id]
    
    def reset_utterance_state(self, participant_id: str):
        """Reset utterance state for participant"""
        if participant_id in self.utterance_states:
            state = self.utterance_states[participant_id]
            old_id = state.utterance_id[:8]
            
            # Track optimization usage for metrics
            if state.sota_optimization_used:
                logger.debug(f"📊 SOTA optimization was used for utterance {old_id}")
            
            # Reset state
            state.buffer.clear()
            state.is_active = False
            state.started_at = None
            state.last_audio_at = None
            state.total_samples = 0
            state.first_partial_sent = False
            state.last_partial_sent_at = None
            state.partial_sequence = 0
            state.utterance_id = str(uuid.uuid4())
            state.ultra_fast_triggered = False
            state.sota_optimization_used = False
            
            logger.debug(f"🔄 SOTA: Reset utterance state: {old_id} → {state.utterance_id[:8]}")
    
    def get_active_participants(self) -> list:
        """Get list of participants with active utterances"""
        return [
            pid for pid, state in self.utterance_states.items() 
            if state.is_active
        ]
    
    def cleanup_participant(self, participant_id: str):
        """Clean up participant state on disconnect"""
        if participant_id in self.utterance_states:
            del self.utterance_states[participant_id]
            logger.debug(f"🧹 Cleaned up utterance state for {participant_id}")
    
    def get_stats(self) -> dict:
        """Get utterance manager statistics"""
        active_count = len(self.get_active_participants())
        total_count = len(self.utterance_states)
        ultra_fast_count = sum(
            1 for state in self.utterance_states.values() 
            if state.ultra_fast_triggered
        )
        optimized_count = sum(
            1 for state in self.utterance_states.values() 
            if state.sota_optimization_used
        )
        
        return {
            "total_participants": total_count,
            "active_utterances": active_count,
            "ultra_fast_triggered": ultra_fast_count,
            "sota_optimized": optimized_count,
            "optimization_rate": f"{(optimized_count / max(1, total_count) * 100):.1f}%"
        }
