"""Security guard service - Phase 2 extraction"""
import logging
from typing import Optional
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class SecurityGuard:
    """Centralized security checks for conversation processing"""
    
    def __init__(self, rate_limiter, circuit_breaker, duplication_detector):
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.duplication_detector = duplication_detector
    
    def ensure_rate_limit(self, user_id: str) -> None:
        """Check rate limit and raise HTTPException if exceeded"""
        if not self.rate_limiter.check_request_rate_limit(user_id):
            logger.warning(f"🚨 Rate limit exceeded for user: {user_id}")
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    def ensure_ai_rate_limit(self, user_id: str) -> None:
        """Check AI-specific rate limit and raise HTTPException if exceeded"""
        if not self.rate_limiter.check_ai_rate_limit(user_id):
            logger.warning(f"🚨 AI rate limit exceeded for user: {user_id}")
            raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    
    def ensure_circuit_closed(self) -> None:
        """Check circuit breaker and raise HTTPException if open"""
        can_call, reason = self.circuit_breaker.should_allow_call()
        if not can_call:
            logger.error(f"🚨 Circuit breaker open: {reason}")
            raise HTTPException(status_code=503, detail=f"Service temporarily unavailable: {reason}")
    
    def ensure_not_duplicate(self, session_id: str, message_id: str, text: str, 
                           participant: str, timestamp: str) -> bool:
        """Check for duplicate messages and return False if duplicate"""
        if self.duplication_detector.is_duplicate_message(
            session_id, message_id, text, participant, timestamp
        ):
            logger.info(f"🚫 Duplicate message blocked: {message_id}")
            return False
        
        # Mark as processed
        self.duplication_detector.mark_message_processed(
            session_id, message_id, text, participant, timestamp
        )
        return True
    
    def get_security_stats(self) -> dict:
        """Get security statistics for monitoring"""
        return {
            "rate_limiter": self.rate_limiter.get_stats(),
            "circuit_breaker": self.circuit_breaker.get_status(),
            "duplication_detector": self.duplication_detector.get_stats()
        }