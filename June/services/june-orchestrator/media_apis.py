# June/services/june-orchestrator/media_apis.py
# Media streaming session and token management APIs

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from shared import require_user_auth, extract_user_id
from token_service import TokenService

logger = logging.getLogger(__name__)

# Initialize router
media_router = APIRouter(prefix="/v1/media", tags=["Media Streaming"])

# Request/Response models
class CreateSessionRequest(BaseModel):
    client_type: str = Field(default="react-native", description="Client type")
    duration_minutes: int = Field(default=30, ge=5, le=60, description="Session duration")

class CreateSessionResponse(BaseModel):
    session_id: str
    expires_at: str
    permissions: List[str]

class GenerateTokenRequest(BaseModel):
    session_id: str
    scopes: Optional[List[str]] = Field(default=None, description="Requested scopes")
    duration_seconds: int = Field(default=300, ge=60, le=900, description="Token duration")

class GenerateTokenResponse(BaseModel):
    token: str
    expires_in: int
    scopes: List[str]
    utterance_id: str

class SessionControlRequest(BaseModel):
    action: str = Field(..., regex="^(start|stop|pause|resume|barge_in)$")
    session_id: str
    reason: Optional[str] = None

# Global token service instance (initialized in main app)
token_service: TokenService = None

def get_token_service() -> TokenService:
    """Dependency to get token service"""
    if token_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token service not initialized"
        )
    return token_service

@media_router.post("/sessions", response_model=CreateSessionResponse)
async def create_media_session(
    request: CreateSessionRequest,
    current_user: dict = Depends(require_user_auth),  # Changed
    token_svc: TokenService = Depends(get_token_service)
):
    user_id = extract_user_id(current_user)  # Use utility function

    """Create a new media streaming session"""
    try:
        user_id = current_user.uid
        
        session_id = token_svc.create_media_session(
            user_id=user_id,
            client_type=request.client_type,
            duration_minutes=request.duration_minutes
        )
        
        session_info = token_svc.get_session_info(session_id)
        
        return CreateSessionResponse(
            session_id=session_id,
            expires_at=session_info["expires_at"],
            permissions=session_info["permissions"]
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to create session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}"
        )

@media_router.post("/tokens", response_model=GenerateTokenResponse)
async def generate_media_token(
    request: GenerateTokenRequest,
    current_user = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service)
):
    """Generate a short-lived token for media streaming"""
    try:
        # Verify session belongs to current user
        session_info = token_svc.get_session_info(request.session_id)
        if not session_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        if session_info["user_id"] != current_user.uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to current user"
            )
        
        token = token_svc.generate_media_token(
            session_id=request.session_id,
            scopes=request.scopes,
            duration_seconds=request.duration_seconds
        )
        
        # Extract info from token for response
        import jwt
        payload = jwt.decode(token, options={"verify_signature": False})
        
        return GenerateTokenResponse(
            token=token,
            expires_in=request.duration_seconds,
            scopes=payload["scope"].split(),
            utterance_id=payload["utterance_id"]
        )
        
    except ValueError as e:
        logger.warning(f"⚠️ Token generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"❌ Token generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate token"
        )

@media_router.get("/sessions/{session_id}")
async def get_session_info(
    session_id: str,
    current_user = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service)
):
    """Get information about a media session"""
    session_info = token_svc.get_session_info(session_id)
    
    if not session_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session_info["user_id"] != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to current user"
        )
    
    return session_info

@media_router.post("/sessions/{session_id}/control")
async def control_media_session(
    session_id: str,
    request: SessionControlRequest,
    current_user = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service)
):
    """Control a media session (start/stop/pause/barge-in)"""
    try:
        # Verify session ownership
        session_info = token_svc.get_session_info(session_id)
        if not session_info or session_info["user_id"] != current_user.uid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        logger.info(f"🎛️ Session control: {request.action} on {session_id}")
        
        # Handle different control actions
        if request.action == "stop":
            token_svc.revoke_session(session_id)
            # TODO: Send stop signal to media relay via Pub/Sub
            
        elif request.action == "barge_in":
            # TODO: Send barge-in signal to media relay
            pass
            
        # TODO: Implement other control actions
        
        return {
            "status": "success",
            "action": request.action,
            "session_id": session_id,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"❌ Session control failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Control action failed: {str(e)}"
        )

@media_router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current_user = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service)
):
    """Revoke a media session"""
    session_info = token_svc.get_session_info(session_id)
    
    if not session_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session_info["user_id"] != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to current user"
        )
    
    success = token_svc.revoke_session(session_id)
    
    return {
        "revoked": success,
        "session_id": session_id
    }

@media_router.get("/sessions")
async def list_user_sessions(
    current_user = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service)
):
    """List all active sessions for current user"""
    user_sessions = [
        session_info for session_info in 
        [token_svc.get_session_info(sid) for sid in token_svc.active_sessions.keys()]
        if session_info and session_info["user_id"] == current_user.uid and session_info["active"]
    ]
    
    return {
        "sessions": user_sessions,
        "total": len(user_sessions)
    }