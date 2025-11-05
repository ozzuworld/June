"""Rate limiting and duplicate message protection"""
import logging
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Advanced rate limiting with user-specific limits"""
    
    def __init__(self):
        self.user_requests: Dict[str, List[datetime]] = defaultdict(list)
        self.user_ai_calls: Dict[str, List[datetime]] = defaultdict(list)
        self.blocked_users: Dict[str, datetime] = {}
        
        # Rate limits
        self.ai_calls_per_minute = 5
        self.ai_calls_per_hour = 50
        self.max_requests_per_minute = 10
        self.block_duration_minutes = 15
        
        logger.info("✅ Rate limiter initialized")
    
    def _cleanup_old_entries(self, user_id: str):
        """Remove old entries to prevent memory bloat"""
        now = datetime.utcnow()
        cutoff_1min = now - timedelta(minutes=1)
        cutoff_1hour = now - timedelta(hours=1)
        
        # Clean requests (1 minute window)
        self.user_requests[user_id] = [
            t for t in self.user_requests[user_id] if t > cutoff_1min
        ]
        
        # Clean AI calls (1 hour window)
        self.user_ai_calls[user_id] = [
            t for t in self.user_ai_calls[user_id] if t > cutoff_1hour
        ]
    
    def _is_user_blocked(self, user_id: str) -> bool:
        """Check if user is temporarily blocked"""
        if user_id not in self.blocked_users:
            return False
        
        block_time = self.blocked_users[user_id]
        if datetime.utcnow() - block_time > timedelta(minutes=self.block_duration_minutes):
            del self.blocked_users[user_id]
            logger.info(f"🔓 Unblocked user {user_id}")
            return False
        
        return True
    
    def check_request_rate_limit(self, user_id: str) -> bool:
        """Check general request rate limit"""
        if self._is_user_blocked(user_id):
            return False
        
        self._cleanup_old_entries(user_id)
        
        # Check requests per minute
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            logger.warning(f"🚫 Request rate limit exceeded for {user_id}")
            self.blocked_users[user_id] = datetime.utcnow()
            return False
        
        self.user_requests[user_id].append(datetime.utcnow())
        return True
    
    def check_ai_rate_limit(self, user_id: str) -> bool:
        """Check AI-specific rate limits (more restrictive)"""
        if self._is_user_blocked(user_id):
            return False
        
        self._cleanup_old_entries(user_id)
        
        now = datetime.utcnow()
        recent_calls = self.user_ai_calls[user_id]
        
        # Check per-minute limit
        calls_last_minute = sum(1 for t in recent_calls if now - t < timedelta(minutes=1))
        if calls_last_minute >= self.ai_calls_per_minute:
            logger.warning(f"🚫 AI rate limit (per-minute) exceeded for {user_id}: {calls_last_minute} calls")
            return False
        
        # Check per-hour limit
        if len(recent_calls) >= self.ai_calls_per_hour:
            logger.warning(f"🚫 AI rate limit (per-hour) exceeded for {user_id}: {len(recent_calls)} calls")
            return False
        
        self.user_ai_calls[user_id].append(now)
        logger.debug(f"✅ AI rate check passed for {user_id} ({calls_last_minute + 1}/min, {len(recent_calls)}/hour)")
        return True
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics"""
        total_users = len(self.user_ai_calls)
        blocked_users = len(self.blocked_users)
        total_ai_calls = sum(len(calls) for calls in self.user_ai_calls.values())
        
        return {
            "total_users_tracked": total_users,
            "blocked_users": blocked_users,
            "total_ai_calls_tracked": total_ai_calls,
            "ai_calls_per_minute_limit": self.ai_calls_per_minute,
            "ai_calls_per_hour_limit": self.ai_calls_per_hour
        }


class DuplicationDetector:
    """Detect and prevent duplicate message processing"""
    
    def __init__(self):
        # Track processed messages per session
        self.session_processed: Dict[str, Set[str]] = defaultdict(set)
        self.session_timestamps: Dict[str, Dict[str, datetime]] = defaultdict(dict)
        self.cleanup_interval = timedelta(minutes=10)
        self.last_cleanup = datetime.utcnow()
        
        logger.info("✅ Duplication detector initialized")
    
    def _cleanup_old_entries(self):
        """Clean up old entries to prevent memory bloat"""
        if datetime.utcnow() - self.last_cleanup < self.cleanup_interval:
            return
        
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        cleaned_sessions = 0
        cleaned_messages = 0
        
        for session_id in list(self.session_timestamps.keys()):
            old_messages = [
                msg_id for msg_id, timestamp in self.session_timestamps[session_id].items()
                if timestamp < cutoff
            ]
            
            for msg_id in old_messages:
                self.session_processed[session_id].discard(msg_id)
                self.session_timestamps[session_id].pop(msg_id, None)
                cleaned_messages += 1
            
            # Remove empty sessions
            if not self.session_processed[session_id]:
                del self.session_processed[session_id]
                if session_id in self.session_timestamps:
                    del self.session_timestamps[session_id]
                cleaned_sessions += 1
        
        self.last_cleanup = datetime.utcnow()
        if cleaned_messages > 0:
            logger.info(f"🧹 Cleaned {cleaned_messages} old messages from {cleaned_sessions} sessions")
    
    def _create_message_hash(self, text: str, participant: str, timestamp: str) -> str:
        """Create a unique hash for message content"""
        content = f"{text}|{participant}|{timestamp}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def is_duplicate_message(self, session_id: str, message_id: Optional[str], 
                           text: str, participant: str, timestamp: str) -> bool:
        """Check if message was already processed"""
        self._cleanup_old_entries()
        
        # Create identifiers
        content_hash = self._create_message_hash(text, participant, timestamp)
        
        # Check both message ID and content hash
        session_processed = self.session_processed[session_id]
        
        if message_id and message_id in session_processed:
            logger.warning(f"🔄 Duplicate message ID detected: {message_id}")
            return True
        
        if content_hash in session_processed:
            logger.warning(f"🔄 Duplicate content detected: {content_hash} (text: {text[:50]}...)")
            return True
        
        return False
    
    def mark_message_processed(self, session_id: str, message_id: Optional[str], 
                             text: str, participant: str, timestamp: str):
        """Mark message as processed"""
        content_hash = self._create_message_hash(text, participant, timestamp)
        now = datetime.utcnow()
        
        # Store both identifiers
        if message_id:
            self.session_processed[session_id].add(message_id)
            self.session_timestamps[session_id][message_id] = now
        
        self.session_processed[session_id].add(content_hash)
        self.session_timestamps[session_id][content_hash] = now
        
        logger.debug(f"✅ Marked message as processed: {content_hash} (session: {session_id})")
    
    def get_stats(self) -> Dict:
        """Get duplication detector statistics"""
        total_sessions = len(self.session_processed)
        total_messages = sum(len(msgs) for msgs in self.session_processed.values())
        
        return {
            "tracked_sessions": total_sessions,
            "tracked_messages": total_messages,
            "last_cleanup": self.last_cleanup.isoformat()
        }


# Global instances
rate_limiter = RateLimiter()
duplication_detector = DuplicationDetector()