# June/services/june-orchestrator/routers/enhanced_conversation_routes.py
# Enhanced conversation routes with TTS audio integration

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import logging
import base64
import asyncio

from shared import require_user_auth, extract_user_id
from enhanced_conversation_manager import EnhancedConversationManager
from models import get_db
from tts_service import get_tts_service, initialize_tts_service
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["Enhanced Conversation"])

# Request/Response Models
class ConversationInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(default="en", description="Language code")
    voice_id: Optional[str] = Field(default=None, description="Preferred voice ID")
    include_audio: bool = Field(default=True, description="Generate TTS audio response")
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0, description="Speech speed")
    extra_extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationOutput(BaseModel):
    ok: bool = True
    message: Dict[str, Any]
    conversation_id: Optional[str] = None
    audio: Optional[Dict[str, Any]] = None  # Audio metadata and data
    processing_time_ms: Optional[int] = None

class VoiceCloneInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    reference_audio_b64: str = Field(..., description="Base64 encoded reference audio")
    language: str = Field(default="EN", description="Language code")

class AudioResponse(BaseModel):
    message_id: str
    audio_available: bool
    audio_size_bytes: Optional[int] = None
    provider: Optional[str] = None
    voice_id: Optional[str] = None
    cached: bool = False

# Initialize conversation manager
async def get_conversation_manager(db: Session = Depends(get_db)) -> EnhancedConversationManager:
    manager = EnhancedConversationManager(db)
    await manager.initialize()
    return manager

# Health and status endpoints
@router.get("/ping")
async def ping():
    return {
        "ok": True, 
        "service": "june-orchestrator-enhanced", 
        "status": "healthy",
        "features": ["tts_integration", "voice_cloning", "audio_responses"]
    }

@router.get("/whoami")
async def whoami(user_payload: Dict[str, Any] = Depends(require_user_auth)):
    """Get current authenticated user information"""
    user_id = extract_user_id(user_payload)
    username = user_payload.get("preferred_username") or user_payload.get("username")
    
    return {
        "ok": True, 
        "subject": username,
        "user_id": user_id,
        "token_present": True,
        "permissions": ["chat", "voice_responses", "voice_cloning"]
    }

@router.get("/tts/status")
async def tts_status(
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Get TTS service status"""
    try:
        status = await manager.get_tts_status()
        return {"ok": True, "tts_status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/tts/voices")
async def get_available_voices(
    language: str = Query(default="EN", description="Language code"),
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Get available TTS voices"""
    try:
        voices = await manager.get_available_voices(language)
        return {"ok": True, "voices": voices}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Main chat endpoint with audio
@router.post("/chat", response_model=ConversationOutput)
async def chat_with_audio(
    payload: ConversationInput,
    user_payload: Dict[str, Any] = Depends(require_user_auth),
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Process a chat message with optional TTS audio response"""
    
    try:
        user_id = extract_user_id(user_payload)
        username = user_payload.get("preferred_username", "user")
        
        logger.info(f"💬 Chat request from {username} ({user_id}): '{payload.text[:50]}...'")
        
        # Get user from database
        user = await manager.get_or_create_user(
            keycloak_id=user_id,
            username=username,
            email=user_payload.get("email")
        )
        
        # Build user preferences
        user_preferences = {
            "preferred_voice": payload.voice_id,
            "speech_speed": payload.speed,
            "language": payload.language
        }
        
        # Process message with optional audio generation
        ai_response, response_metadata, audio_bytes = await manager.process_user_message_with_audio(
            user=user,
            user_message=payload.text,
            audio_metadata=payload.extra_metadata,
            generate_tts_response=payload.include_audio,
            user_preferences=user_preferences
        )
        
        # Prepare response
        response_data = ConversationOutput(
            ok=True,
            message={
                "text": ai_response,
                "role": "assistant",
                "type": "text",
                "timestamp": response_metadata.get("timestamp")
            },
            conversation_id=response_metadata.get("conversation_id"),
            processing_time_ms=response_metadata.get("processing_time")
        )
        
        # Add audio data if available
        if audio_bytes and payload.include_audio:
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            response_data.audio = {
                "data": audio_b64,
                "content_type": "audio/wav",
                "size_bytes": len(audio_bytes),
                "provider": response_metadata.get("audio_provider"),
                "voice_id": response_metadata.get("audio_voice_id"),
                "processing_time_ms": response_metadata.get("audio_processing_time_ms"),
                "cached": response_metadata.get("audio_cached", False)
            }
            
            logger.info(f"🎵 Audio response generated: {len(audio_bytes)} bytes")
        
        logger.info(f"\u2705 Chat response sent to {username}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e

# Voice cloning endpoint
@router.post("/chat/clone", response_model=ConversationOutput)
async def chat_with_voice_clone(
    payload: VoiceCloneInput,
    user_payload: Dict[str, Any] = Depends(require_user_auth),
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Generate speech using voice cloning from reference audio"""
    
    try:
        user_id = extract_user_id(user_payload)
        username = user_payload.get("preferred_username", "user")
        
        logger.info(f"🎤 Voice clone request from {username}: '{payload.text[:50]}...'")
        
        # Get user from database
        user = await manager.get_or_create_user(
            keycloak_id=user_id,
            username=username,
            email=user_payload.get("email")
        )
        
        # Decode reference audio
        try:
            reference_audio_bytes = base64.b64decode(payload.reference_audio_b64)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 audio data: {e}"
            )
        
        # Get TTS service and clone voice
        tts_service = get_tts_service()
        audio_response = await tts_service.clone_voice_for_response(
            text=payload.text,
            reference_audio_bytes=reference_audio_bytes,
            language=payload.language
        )
        
        # Prepare response
        audio_b64 = base64.b64encode(audio_response.audio_data).decode('utf-8')
        
        response_data = ConversationOutput(
            ok=True,
            message={
                "text": payload.text,
                "role": "assistant",
                "type": "cloned_voice"
            },
            audio={
                "data": audio_b64,
                "content_type": audio_response.content_type,
                "size_bytes": len(audio_response.audio_data),
                "provider": audio_response.provider,
                "voice_id": audio_response.voice_id,
                "processing_time_ms": audio_response.processing_time_ms,
                "cloned": True
            },
            processing_time_ms=audio_response.processing_time_ms
        )
        
        logger.info(f"✅ Voice cloning completed for {username}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice cloning failed: {str(e)}",
        ) from e

# Audio regeneration endpoint
@router.post("/messages/{message_id}/regenerate-audio")
async def regenerate_message_audio(
    message_id: str,
    voice_id: Optional[str] = None,
    speed: Optional[float] = None,
    user_payload: Dict[str, Any] = Depends(require_user_auth),
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Regenerate TTS audio for an existing message"""
    
    try:
        user_id = extract_user_id(user_payload)
        
        # Build user preferences
        user_preferences = {}
        if voice_id:
            user_preferences["preferred_voice"] = voice_id
        if speed:
            user_preferences["speech_speed"] = speed
        
        # Regenerate audio
        audio_response = await manager.regenerate_audio_for_message(
            message_id=message_id,
            voice=voice_id,
            speed=speed,
            user_preferences=user_preferences
        )
        
        if not audio_response:
            raise HTTPException(status_code=404, detail="Message not found or audio generation failed")
        
        # Return audio data
        audio_b64 = base64.b64encode(audio_response.audio_data).decode('utf-8')
        
        return {
            "ok": True,
            "message_id": message_id,
            "audio": {
                "data": audio_b64,
                "content_type": audio_response.content_type,
                "size_bytes": len(audio_response.audio_data),
                "provider": audio_response.provider,
                "voice_id": audio_response.voice_id,
                "processing_time_ms": audio_response.processing_time_ms,
                "regenerated": True
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Audio regeneration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audio regeneration failed: {str(e)}",
        ) from e

# Binary audio endpoint for streaming
@router.get("/messages/{message_id}/audio")
async def get_message_audio(
    message_id: str,
    regenerate: bool = Query(default=False, description="Regenerate audio if needed"),
    voice_id: Optional[str] = Query(default=None),
    speed: Optional[float] = Query(default=None),
    user_payload: Dict[str, Any] = Depends(require_user_auth),
    manager: EnhancedConversationManager = Depends(get_conversation_manager)
):
    """Get audio data for a message as binary response"""
    
    try:
        # This would fetch audio from database or regenerate if needed
        # For now, return a placeholder
        
        if regenerate:
            audio_response = await manager.regenerate_audio_for_message(
                message_id=message_id,
                voice=voice_id,
                speed=speed
            )
        else:
            # Would fetch from database in real implementation
            raise HTTPException(status_code=404, detail="Audio not found for message")
        
        return Response(
            content=audio_response.audio_data,
            media_type="audio/wav",
            headers={
                "Content-Length": str(len(audio_response.audio_data)),
                "X-Message-ID": message_id,
                "X-Voice-ID": audio_response.voice_id,
                "X-Provider": audio_response.provider
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Audio retrieval failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audio retrieval failed: {str(e)}",
        ) from e