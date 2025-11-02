"""Natural conversation flow logic - Phase 2 extraction"""
import os
import logging
from typing import Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# Natural conversation flow settings (extracted from original webhooks.py)
NATURAL_FLOW_ENABLED = os.getenv("NATURAL_FLOW_ENABLED", "true").lower() == "true"
NATURAL_FLOW_FOR_FINALS = os.getenv("NATURAL_FLOW_FOR_FINALS", "true").lower() == "true"
UTTERANCE_MIN_LENGTH = int(os.getenv("UTTERANCE_MIN_LENGTH", "15"))
UTTERANCE_MIN_PAUSE_MS = int(os.getenv("UTTERANCE_MIN_PAUSE_MS", "1500"))
SENTENCE_BUFFER_ENABLED = os.getenv("SENTENCE_BUFFER_ENABLED", "true").lower() == "true"
LLM_TRIGGER_THRESHOLD = float(os.getenv("LLM_TRIGGER_THRESHOLD", "0.7"))
FINAL_TRANSCRIPT_COOLDOWN_MS = int(os.getenv("FINAL_TRANSCRIPT_COOLDOWN_MS", "2000"))


class UtteranceStateManager:
    """Manages utterance states for natural conversation flow"""
    
    def __init__(self):
        self._utterance_states: Dict[str, Dict[str, Any]] = {}
        
    def get_or_create_state(self, participant: str, utterance_id: str) -> Dict[str, Any]:
        """Get or create utterance state for tracking natural flow"""
        key = f"{participant}:{utterance_id}"
        
        if key not in self._utterance_states:
            self._utterance_states[key] = {
                "participant": participant,
                "utterance_id": utterance_id,
                "started_at": datetime.utcnow(),
                "last_partial_at": datetime.utcnow(),
                "partials": [],
                "processing_started": False,
                "last_significant_length": 0,
                "pause_detected": False
            }
            
        return self._utterance_states[key]
    
    def add_partial(self, participant: str, utterance_id: str, text: str, 
                   sequence: int, confidence: float = 0.0) -> bool:
        """Add partial and return if this represents significant progress"""
        state = self.get_or_create_state(participant, utterance_id)
        now = datetime.utcnow()
        state["last_partial_at"] = now
        
        # Only add if significantly different from last
        if not state["partials"] or len(text) > len(state["partials"][-1]) + 3:
            state["partials"].append(text)
            return True
        return False
    
    def should_start_processing(self, participant: str, utterance_id: str, 
                              text: str, confidence: float = 0.0) -> bool:
        """Determine if we should start LLM processing based on natural cues"""
        state = self.get_or_create_state(participant, utterance_id)
        
        if state["processing_started"]:
            return False
            
        # Don't process very short utterances
        if len(text.strip()) < UTTERANCE_MIN_LENGTH:
            return False
            
        # Check for natural conversation boundaries
        words = text.lower().strip().split()
        
        # Look for sentence endings
        sentence_endings = ['.', '!', '?']
        if any(text.strip().endswith(end) for end in sentence_endings):
            logger.info(f"🎯 Natural sentence ending detected: '{text[-20:]}'") 
            return True
            
        # Look for question patterns
        question_starters = ['what', 'how', 'why', 'when', 'where', 'who', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does']
        if len(words) >= 3 and words[0] in question_starters:
            if len(text.strip()) >= 20:  # Wait for substantial question
                logger.info(f"🎯 Question pattern detected: '{text[:30]}...'")
                return True
                
        # Look for natural pauses (time gap between partials)
        time_since_start = (datetime.utcnow() - state["started_at"]).total_seconds() * 1000
        if time_since_start >= UTTERANCE_MIN_PAUSE_MS and len(text.strip()) >= 25:
            logger.info(f"🎯 Natural pause detected after {time_since_start:.0f}ms: '{text[:30]}...'")
            return True
            
        # High confidence longer phrases
        if confidence >= LLM_TRIGGER_THRESHOLD and len(text.strip()) >= 30:
            logger.info(f"🎯 High confidence utterance detected: {confidence:.2f} '{text[:30]}...'")
            return True
            
        return False
    
    def mark_processing_started(self, participant: str, utterance_id: str):
        """Mark that LLM processing has started for this utterance"""
        state = self.get_or_create_state(participant, utterance_id)
        state["processing_started"] = True
    
    def get_current_text(self, participant: str, utterance_id: str) -> str:
        """Get the most recent partial text"""
        state = self.get_or_create_state(participant, utterance_id)
        return state["partials"][-1] if state["partials"] else ""
    
    def cleanup_expired(self, timeout_seconds: int = 30) -> int:
        """Clean up expired utterance states"""
        now = datetime.utcnow()
        expired_keys = []
        
        for key, state in self._utterance_states.items():
            age = (now - state["started_at"]).total_seconds()
            if age > timeout_seconds:
                expired_keys.append(key)
                
        for key in expired_keys:
            del self._utterance_states[key]
            
        if expired_keys:
            logger.debug(f"🧹 Cleaned {len(expired_keys)} expired utterance states")
            
        return len(expired_keys)


class FinalTranscriptTracker:
    """Track timing of final transcripts to prevent rapid-fire responses"""
    
    def __init__(self):
        self._trackers: Dict[str, Dict[str, Any]] = {}
    
    def should_process_final_transcript(self, participant: str, text: str, 
                                      confidence: float = 0.0) -> Tuple[bool, str]:
        """Determine if this final transcript should be processed based on natural timing"""
        now = datetime.utcnow()
        
        # Get or create tracker for participant
        if participant not in self._trackers:
            self._trackers[participant] = {
                "last_final_transcript": None,
                "last_processing_time": None,
                "transcript_count": 0
            }
        
        tracker = self._trackers[participant]
        
        # Always process the first final transcript
        if tracker["last_final_transcript"] is None:
            tracker["last_final_transcript"] = now
            tracker["transcript_count"] = 1
            return True, "first transcript"
            
        # Check cooldown period
        time_since_last = (now - tracker["last_final_transcript"]).total_seconds() * 1000
        if time_since_last < FINAL_TRANSCRIPT_COOLDOWN_MS:
            logger.info(f"🕰️ Final transcript cooldown active: {time_since_last:.0f}ms < {FINAL_TRANSCRIPT_COOLDOWN_MS}ms")
            return False, f"cooldown active ({time_since_last:.0f}ms)"
            
        # Apply natural conversation logic to final transcripts too
        words = text.lower().strip().split()
        
        # Don't process very short final transcripts
        if len(text.strip()) < UTTERANCE_MIN_LENGTH:
            logger.info(f"🚫 Final transcript too short: '{text}' ({len(text.strip())} chars)")
            return False, f"too short ({len(text.strip())} chars)"
            
        # Look for sentence endings - these should be processed
        sentence_endings = ['.', '!', '?']
        if any(text.strip().endswith(end) for end in sentence_endings):
            logger.info(f"🎯 Final transcript with natural ending: '{text[-20:]}'") 
            tracker["last_final_transcript"] = now
            tracker["transcript_count"] += 1
            return True, "natural sentence ending"
            
        # Look for question patterns
        question_starters = ['what', 'how', 'why', 'when', 'where', 'who', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does']
        if len(words) >= 3 and words[0] in question_starters and len(text.strip()) >= 20:
            logger.info(f"🎯 Final transcript question pattern: '{text[:30]}...'")
            tracker["last_final_transcript"] = now
            tracker["transcript_count"] += 1
            return True, "question pattern"
            
        # High confidence substantial content
        if confidence >= LLM_TRIGGER_THRESHOLD and len(text.strip()) >= 30:
            logger.info(f"🎯 Final transcript high confidence: {confidence:.2f} '{text[:30]}...'")
            tracker["last_final_transcript"] = now
            tracker["transcript_count"] += 1
            return True, "high confidence"
            
        # Default: don't process fragmented final transcripts
        logger.info(f"🚫 Final transcript filtered: '{text}' (fragmented/incomplete)")
        return False, "fragmented or incomplete"
    
    def reset_tracker(self, participant: str):
        """Reset the tracker for a participant"""
        if participant in self._trackers:
            del self._trackers[participant]
    
    def cleanup_expired(self, timeout_minutes: int = 5) -> int:
        """Clean up trackers after inactivity"""
        now = datetime.utcnow()
        expired_participants = []
        
        for participant, tracker in self._trackers.items():
            if tracker["last_final_transcript"]:
                age_minutes = (now - tracker["last_final_transcript"]).total_seconds() / 60
                if age_minutes > timeout_minutes:
                    expired_participants.append(participant)
                    
        for participant in expired_participants:
            del self._trackers[participant]
            
        if expired_participants:
            logger.debug(f"🧹 Cleaned {len(expired_participants)} expired final transcript trackers")
            
        return len(expired_participants)


class SentenceBuffer:
    """Buffer tokens and only emit complete sentences to TTS for natural speech"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = ['.', '!', '?']
        self.sentence_count = 0
        
    def add_token(self, token: str) -> Optional[str]:
        """Add token and return complete sentence if ready"""
        self.buffer += token
        
        # Look for sentence boundaries
        for ending in self.sentence_endings:
            if ending in self.buffer:
                # Find the sentence boundary
                end_pos = self.buffer.find(ending)
                if end_pos != -1:
                    # Extract the complete sentence
                    sentence = self.buffer[:end_pos + 1].strip()
                    self.buffer = self.buffer[end_pos + 1:].strip()  # Keep remainder
                    
                    # Only return substantial sentences
                    if len(sentence) >= 10:
                        self.sentence_count += 1
                        logger.info(f"📝 Complete sentence #{self.sentence_count} buffered: '{sentence[:50]}...'")
                        return sentence
        
        return None  # No complete sentence yet
        
    def get_remaining(self) -> str:
        """Get any remaining buffered content"""
        return self.buffer.strip()
        
    def clear(self):
        """Clear the buffer"""
        self.buffer = ""


# Convenience functions for use in processor
def should_start_online_llm(utterance_manager: UtteranceStateManager, 
                           participant: str, utterance_id: str, 
                           text: str, confidence: float = 0.0) -> bool:
    """Natural conversation flow: only start LLM on complete thoughts"""
    if not NATURAL_FLOW_ENABLED:
        # Fallback to original logic if natural flow is disabled
        return len(text.strip()) >= 10
        
    return utterance_manager.should_start_processing(participant, utterance_id, text, confidence)


def should_process_final_transcript(final_tracker: FinalTranscriptTracker,
                                  participant: str, text: str, 
                                  confidence: float = 0.0) -> Tuple[bool, str]:
    """Natural flow for final transcripts: prevent rapid-fire responses"""
    if not NATURAL_FLOW_FOR_FINALS:
        return True, "natural flow disabled for finals"
        
    return final_tracker.should_process_final_transcript(participant, text, confidence)