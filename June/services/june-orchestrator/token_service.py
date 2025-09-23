# June/services/june-orchestrator/token_service.py
# Token generation and session management for direct media streaming

import os
import jwt
import time
import uuid
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class MediaSession:
    session_id: str
    user_id: str
    client_type: str  # "react-native", "web", etc.
    created_at: datetime
    expires_at: datetime
    active: bool = True
    permissions: List[str] = None

class TokenService:
    """Generates short-lived tokens for direct media streaming"""
    
    def __init__(self, keycloak_service):
        self.keycloak = keycloak_service
        self.signing_key = self._get_signing_key()
        self.issuer = os.getenv("KC_HOSTNAME_URL", "https://june-idp.allsafe.world") + "/auth/realms/june"
        self.active_sessions: Dict[str, MediaSession] = {}
        
    def _get_signing_key(self) -> str:
        """Get the private key for signing tokens"""
        # In production, get this from Keycloak's realm keys
        # For now, use a symmetric key from environment
        return os.getenv("JWT_SIGNING_KEY", "your-secret-key-change-in-production")
    
    def create_media_session(
        self, 
        user_id: str, 
        client_type: str = "react-native",
        duration_minutes: int = 30
    ) -> str:
        """Create a new media session"""
        session_id = f"session_{uuid.uuid4().hex[:16]}"
        
        session = MediaSession(
            session_id=session_id,
            user_id=user_id,
            client_type=client_type,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=duration_minutes),
            permissions=["asr:stream:write", "tts:stream:read", "session:control"]
        )
        
        self.active_sessions[session_id] = session
        
        logger.info(f"✅ Created media session: {session_id} for user: {user_id}")
        return session_id
    
    def generate_media_token(
        self, 
        session_id: str, 
        scopes: List[str] = None,
        duration_seconds: int = 300  # 5 minutes default
    ) -> str:
        """Generate a short-lived token for media streaming"""
        
        session = self.active_sessions.get(session_id)
        if not session or not session.active:
            raise ValueError(f"Invalid or inactive session: {session_id}")
        
        if datetime.utcnow() > session.expires_at:
            raise ValueError(f"Session expired: {session_id}")
        
        # Default scopes if not specified
        if scopes is None:
            scopes = ["asr:stream:write", "tts:stream:read"]
        
        # Validate requested scopes against session permissions
        if not all(scope in session.permissions for scope in scopes):
            raise ValueError(f"Insufficient permissions for scopes: {scopes}")
        
        now = int(time.time())
        utterance_id = f"utt_{uuid.uuid4().hex[:12]}"
        
        payload = {
            "iss": self.issuer,
            "sub": session.user_id,
            "aud": "media-relay",
            "iat": now,
            "exp": now + duration_seconds,
            "scope": " ".join(scopes),
            "sid": session_id,
            "utterance_id": utterance_id,
            "client_type": session.client_type,
            "jti": f"jwt_{uuid.uuid4().hex[:16]}"  # JWT ID for revocation
        }
        
        token = jwt.encode(payload, self.signing_key, algorithm="HS256")
        
        logger.info(f"🎫 Generated media token for session: {session_id}, utterance: {utterance_id}")
        return token
    
    def validate_token(self, token: str) -> Dict:
        """Validate a media token and return claims"""
        try:
            payload = jwt.decode(
                token, 
                self.signing_key, 
                algorithms=["HS256"],
                audience="media-relay",
                issuer=self.issuer
            )
            
            # Check if session is still active
            session_id = payload.get("sid")
            session = self.active_sessions.get(session_id)
            
            if not session or not session.active:
                raise jwt.InvalidTokenError("Session inactive")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("🚫 Expired media token")
            raise
        except jwt.InvalidTokenError as e:
            logger.warning(f"🚫 Invalid media token: {e}")
            raise
    
    def revoke_session(self, session_id: str) -> bool:
        """Revoke a media session and all its tokens"""
        session = self.active_sessions.get(session_id)
        if session:
            session.active = False
            logger.info(f"🔒 Revoked session: {session_id}")
            return True
        return False
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        now = datetime.utcnow()
        expired = [
            sid for sid, session in self.active_sessions.items()
            if now > session.expires_at
        ]
        
        for session_id in expired:
            del self.active_sessions[session_id]
            logger.info(f"🧹 Cleaned up expired session: {session_id}")
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Get information about a session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None
        
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "client_type": session.client_type,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "active": session.active,
            "permissions": session.permissions
        }