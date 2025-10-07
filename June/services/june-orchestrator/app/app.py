"""
June Orchestrator - Simplified and Clean
Handles AI chat, TTS, and STT webhook integration
"""
import time
import base64
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Import our clean modules
from app.config import get_config
from app.auth import verify_service_token, verify_user_token, extract_user_id
from app.ai_service import generate_ai_response, is_ai_available
from app.storage import add_message, get_conversation, get_stats
from app.tts_client import get_tts_client

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create app
config = get_config()
app = FastAPI(
    title="June Orchestrator",
    version="5.0.0",
    description="Simplified AI Orchestrator"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================================
# DATA MODELS
# ============================================================================

class AudioConfig(BaseModel):
    """Audio configuration for TTS"""
    voice: str = Field(default="default")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="EN")


class ChatRequest(BaseModel):
    """Chat request from frontend"""
    text: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(default="en")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1, le=4000)
    include_audio: bool = Field(default=False)
    audio_config: Optional[AudioConfig] = None


class TranscriptFromSTT(BaseModel):
    """Transcript received from STT service"""
    transcript_id: str
    user_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    metadata: dict = {}


class ChatResponse(BaseModel):
    """Chat response to frontend"""
    ok: bool
    message: dict  # {"text": "...", "role": "assistant"}
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"
    audio: Optional[dict] = None


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Service information"""
    tts_status = await get_tts_client().get_status()
    storage_stats = get_stats()
    
    return {
        "service": "June Orchestrator",
        "version": "5.0.0",
        "status": "healthy",
        "features": {
            "ai_chat": is_ai_available(),
            "text_to_speech": tts_status.get("available", False),
            "stt_webhook": True,
            "conversation_memory": True
        },
        "storage": storage_stats,
        "endpoints": {
            "health": "/healthz",
            "user_chat": "/v1/chat",
            "stt_webhook": "/v1/stt/webhook",
            "conversation": "/v1/conversations/{user_id}"
        }
    }


@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "5.0.0",
        "timestamp": time.time(),
        "ai_available": is_ai_available()
    }


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    auth_data: dict = Depends(verify_user_token)
):
    """
    User chat endpoint (when user types text)
    
    Flow:
    1. User types message
    2. Generate AI response
    3. Optionally generate TTS audio
    4. Store in conversation history
    5. Return response
    """
    start_time = time.time()
    user_id = extract_user_id(auth_data)
    
    logger.info(f"💬 Chat from {user_id}: {request.text[:50]}...")
    
    try:
        # Get conversation history
        history = await get_conversation(user_id)
        
        # Generate AI response
        ai_response = await generate_ai_response(
            text=request.text,
            user_id=user_id,
            conversation_history=history,
            language=request.language
        )
        
        # Store messages
        await add_message(user_id, "user", request.text)
        await add_message(user_id, "assistant", ai_response)
        
        # Build response
        response_time = int((time.time() - start_time) * 1000)
        
        chat_response = ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{user_id}-{int(time.time())}",
            ai_provider="gemini" if is_ai_available() else "fallback"
        )
        
        # Generate TTS audio if requested
        if request.include_audio:
            audio_config = request.audio_config or AudioConfig()
            
            try:
                tts_client = get_tts_client()
                audio_result = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice=audio_config.voice,
                    speed=audio_config.speed,
                    language=audio_config.language
                )
                
                if "error" in audio_result:
                    logger.warning(f"⚠️ TTS failed: {audio_result['error']}")
                    chat_response.audio = {"error": audio_result["error"]}
                else:
                    audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                    chat_response.audio = {
                        "data": audio_b64,
                        "content_type": audio_result["content_type"],
                        "size_bytes": audio_result["size_bytes"],
                        "voice": audio_result["voice"],
                        "speed": audio_result["speed"],
                        "language": audio_result["language"]
                    }
                    logger.info(f"✅ TTS generated: {audio_result['size_bytes']} bytes")
            
            except Exception as e:
                logger.error(f"❌ TTS generation error: {e}")
                chat_response.audio = {"error": f"TTS failed: {str(e)}"}
        
        logger.info(f"✅ Chat response sent to {user_id} ({response_time}ms)")
        return chat_response
    
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"Error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )


@app.post("/v1/stt/webhook")
async def stt_webhook(
    transcript: TranscriptFromSTT,
    background_tasks: BackgroundTasks,
    service_auth: dict = Depends(verify_service_token)
):
    """
    STT webhook endpoint with TTS generation
    
    Flow:
    1. User speaks → STT transcribes
    2. STT sends transcript here
    3. Generate AI response
    4. Generate TTS audio for voice-to-voice flow
    5. Store in conversation
    6. Return response with audio
    """
    start_time = time.time()
    logger.info(f"🎙️ Transcript from {transcript.user_id}: {transcript.text}")
    
    try:
        # Get conversation history
        history = await get_conversation(transcript.user_id)
        
        # Generate AI response
        ai_response = await generate_ai_response(
            text=transcript.text,
            user_id=transcript.user_id,
            conversation_history=history,
            language=transcript.language or "en"
        )
        
        # Store messages
        await add_message(transcript.user_id, "user", transcript.text)
        await add_message(transcript.user_id, "assistant", ai_response)
        
        # FIXED: Generate TTS audio for voice-to-voice flow
        audio_data = None
        try:
            logger.info(f"🔊 Generating TTS audio for response: {ai_response[:50]}...")
            tts_client = get_tts_client()
            
            # Map language codes if needed
            tts_language = "EN"
            if transcript.language:
                lang_map = {
                    "en": "EN", "english": "EN",
                    "es": "ES", "spanish": "ES", 
                    "fr": "FR", "french": "FR",
                    "de": "DE", "german": "DE",
                    "it": "IT", "italian": "IT",
                    "pt": "PT", "portuguese": "PT",
                    "zh": "ZH", "chinese": "ZH"
                }
                tts_language = lang_map.get(transcript.language.lower(), "EN")
            
            audio_result = await tts_client.synthesize_speech(
                text=ai_response,
                voice="default",
                speed=1.0,
                language=tts_language
            )
            
            if "error" not in audio_result:
                audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                audio_data = {
                    "data": audio_b64,
                    "content_type": audio_result["content_type"],
                    "size_bytes": audio_result["size_bytes"],
                    "voice": audio_result.get("voice", "default"),
                    "speed": audio_result.get("speed", 1.0),
                    "language": audio_result.get("language", tts_language)
                }
                logger.info(f"✅ TTS generated: {audio_result['size_bytes']} bytes for voice response")
            else:
                logger.warning(f"⚠️ TTS failed: {audio_result['error']}")
                audio_data = {"error": audio_result["error"]}
        
        except Exception as e:
            logger.error(f"❌ TTS generation error: {e}")
            audio_data = {"error": f"TTS failed: {str(e)}"}
        
        processing_time = int((time.time() - start_time) * 1000)
        logger.info(f"✅ Processed transcript {transcript.transcript_id} ({processing_time}ms)")
        
        return {
            "status": "success",
            "transcript_id": transcript.transcript_id,
            "user_id": transcript.user_id,
            "ai_response": ai_response,
            "audio": audio_data,  # FIXED: Include audio in response
            "processing_time_ms": processing_time,
            "message": "Transcript processed with voice response"
        }
    
    except Exception as e:
        logger.error(f"❌ STT webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/conversations/{user_id}")
async def get_user_conversation(
    user_id: str,
    auth_data: dict = Depends(verify_user_token),
    limit: int = 20
):
    """
    Get conversation history for user
    Frontend can poll this to get latest messages
    """
    authenticated_user = extract_user_id(auth_data)
    
    # Users can only see their own conversations
    if authenticated_user != user_id and authenticated_user != "anonymous":
        raise HTTPException(status_code=403, detail="Access denied")
    
    messages = await get_conversation(user_id, limit=limit)
    
    return {
        "user_id": user_id,
        "total_messages": len(messages),
        "messages": messages,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/v1/tts/status")
async def tts_status():
    """Check TTS service status"""
    tts_client = get_tts_client()
    return await tts_client.get_status()


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup"""
    logger.info("🚀 Starting June Orchestrator v5.0.0")
    logger.info(f"AI Available: {is_ai_available()}")
    
    tts_status = await get_tts_client().get_status()
    logger.info(f"TTS Available: {tts_status.get('available', False)}")
    
    logger.info("✅ Orchestrator ready")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config["port"], log_level="info")
