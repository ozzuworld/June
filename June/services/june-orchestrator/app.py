# June/services/june-orchestrator/app.py - Enhanced for Phase 2
# Conversation management, tool system, and database integration

import os
import json
import uuid
import asyncio
import logging
import time
import base64
from typing import Optional, Dict, Any
from datetime import datetime

import httpx
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

# Import Phase 1 components (existing)
from shared.auth_service import create_service_auth_client, require_service_auth, ServiceAuthClient
from authz import get_current_user
from external_tts_client import ExternalTTSClient

# Import Phase 2 components (new)
from models import create_tables, get_db, User
from conversation_manager import ConversationOrchestrator
from media_apis import media_router, token_service as global_token_service
from token_service import TokenService

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Environment Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:june_db_pass_2024@postgresql:5432/june_db")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_SHARED_SECRET", "")

# AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Service URLs
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "")
EXTERNAL_TTS_URL = os.getenv("EXTERNAL_TTS_URL", "")
MEDIA_RELAY_URL = os.getenv("MEDIA_RELAY_URL", "http://june-media-relay:8080")

# Decode external TTS URL if base64 encoded
if EXTERNAL_TTS_URL:
    try:
        decoded_url = base64.b64decode(EXTERNAL_TTS_URL).decode('utf-8')
        if decoded_url.startswith('http'):
            EXTERNAL_TTS_URL = decoded_url
            logger.info("✅ Decoded external TTS URL from base64")
    except Exception:
        pass

# Initialize AI model (existing code)
ai_model = None
try:
    if GEMINI_API_KEY:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        
        genai.configure(api_key=GEMINI_API_KEY)
        
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 1024,
        }
        
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }
        
        ai_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            safety_settings=safety_settings,
        )
        
        logger.info("✅ Gemini AI model initialized")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not set - using fallback responses")
except ImportError:
    logger.warning("⚠️ google-generativeai not installed - using fallback responses")
except Exception as e:
    logger.error(f"⚠️ Failed to initialize AI model: {e}")

# Global components
service_auth = None
stt_client = None
tts_client = None
token_svc = None
conversation_orchestrator = None

# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    # Startup
    logger.info("🚀 Starting June Orchestrator v2.0 (Phase 2)")
    
    # Create database tables
    create_tables()
    
    # Initialize service authentication
    global service_auth, stt_client, tts_client, token_svc, conversation_orchestrator
    
    if service_auth:
        # Initialize conversation orchestrator with database
        from models import SessionLocal
        db = SessionLocal()
        try:
            conversation_orchestrator = ConversationOrchestrator(db)
            await conversation_orchestrator.initialize()
            logger.info("✅ Conversation orchestrator initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize conversation orchestrator: {e}")
        finally:
            db.close()
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down June Orchestrator")

# FastAPI app with lifespan
app = FastAPI(
    title="June Orchestrator v2.0", 
    version="2.0.0",
    description="Enhanced AI Platform with Conversation Management",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enhanced STT Client (existing)
class AuthenticatedSTTClient:
    """STT client with authentication and proper error handling"""
    
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
        self.is_available = True
        self.last_health_check = 0
    
    async def health_check(self) -> bool:
        """Check if STT service is available"""
        now = time.time()
        if now - self.last_health_check < 30:
            return self.is_available
        
        try:
            response = await self.auth.make_authenticated_request(
                "GET", f"{self.base_url}/healthz", timeout=5.0
            )
            self.is_available = response.status_code == 200
            self.last_health_check = now
            return self.is_available
        except Exception as e:
            logger.warning(f"STT health check failed: {e}")
            self.is_available = False
            self.last_health_check = now
            return False
    
    async def transcribe(self, audio_data: bytes, language: str = "en-US") -> dict:
        """Transcribe audio using STT service"""
        try:
            if not await self.health_check():
                return {"text": "STT service unavailable", "confidence": 0.0, "error": "service_unavailable"}
            
            response = await self.auth.make_authenticated_request(
                "POST", f"{self.base_url}/v1/transcribe",
                files={"audio": ("audio.m4a", audio_data, "audio/mp4")},
                data={"language": language},
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("text", "Could not transcribe audio"),
                    "confidence": result.get("confidence", 0.0),
                    "method": result.get("method", "unknown"),
                    "success": True
                }
            else:
                logger.error(f"STT service error: {response.status_code}")
                return {"text": "Transcription service error", "confidence": 0.0, "error": f"http_{response.status_code}", "success": False}
                
        except Exception as e:
            logger.error(f"STT client error: {e}")
            return {"text": "STT service error", "confidence": 0.0, "error": str(e), "success": False}

# Enhanced health check
@app.get("/healthz")
async def healthz():
    """Enhanced health check endpoint"""
    health_status = {
        "ok": True,
        "service": "june-orchestrator",
        "version": "2.0.0",
        "timestamp": time.time(),
        "status": "healthy",
        "components": {
            "ai_model": ai_model is not None,
            "service_auth": service_auth is not None,
            "stt_client": stt_client is not None,
            "tts_client": tts_client is not None,
            "external_tts_url": EXTERNAL_TTS_URL != "",
            "token_service": token_svc is not None,
            "media_relay": MEDIA_RELAY_URL != "",
            "database": True,  # TODO: Add actual DB health check
            "conversation_orchestrator": conversation_orchestrator is not None
        },
        "database_url": DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else "configured",
        "features": {
            "conversation_management": True,
            "tool_system": True,
            "media_streaming": True,
            "token_generation": True,
            "session_management": True,
            "data_collection": True
        }
    }
    
    # Check external dependencies
    if stt_client:
        health_status["components"]["stt_available"] = await stt_client.health_check()
    
    if tts_client:
        try:
            health_status["components"]["external_tts_available"] = await tts_client.health_check()
        except Exception:
            health_status["components"]["external_tts_available"] = False
    
    # Overall health
    critical_components = ["ai_model", "service_auth", "database", "conversation_orchestrator"]
    health_status["ok"] = all(health_status["components"].get(comp, False) for comp in critical_components)
    
    if not health_status["ok"]:
        health_status["status"] = "degraded"
    
    return health_status

# NEW: Enhanced conversation endpoint
@app.post("/v1/conversation")
async def process_conversation(
    payload: dict,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enhanced conversation processing with persistence"""
    
    start_time = datetime.now()
    
    response = {
        "transcription": "",
        "transcription_confidence": 0.0,
        "response_text": "",
        "response_audio": None,
        "conversation_id": None,
        "message_id": None,
        "tool_used": False,
        "processing_complete": False,
        "has_audio": False,
        "errors": [],
        "warnings": [],
        "processing_time": 0
    }
    
    try:
        # Get or create user from Keycloak info
        user = await conversation_orchestrator.conversation_manager.get_or_create_user(
            keycloak_id=current_user.uid,
            username=current_user.email or "unknown",
            email=current_user.email
        )
        
        # Get audio data
        audio_data = payload.get("audio_data")
        if not audio_data:
            response["errors"].append("No audio data provided")
            response["response_text"] = "Please provide audio data"
            return response
        
        try:
            audio_bytes = base64.b64decode(audio_data)
            logger.info(f"📊 Received audio: {len(audio_bytes)} bytes")
        except Exception as decode_error:
            response["errors"].append(f"Audio decode error: {decode_error}")
            return response
        
        # Step 1: Transcribe audio
        transcription_result = await stt_client.transcribe(audio_bytes, "en-US") if stt_client else {
            "text": "Hello, how can I help you?", "confidence": 0.5, "success": False
        }
        
        transcription_text = transcription_result.get("text", "Hello")
        response["transcription"] = transcription_text
        response["transcription_confidence"] = transcription_result.get("confidence", 0.0)
        
        # Step 2: Process through enhanced conversation system
        audio_metadata = {
            "size": len(audio_bytes),
            "format": "m4a",
            "duration_estimate": len(audio_bytes) / 32000
        }
        
        ai_response, metadata = await conversation_orchestrator.process_user_message(
            user, transcription_text, audio_metadata
        )
        
        response["response_text"] = ai_response
        response["conversation_id"] = metadata["conversation_id"]
        response["message_id"] = metadata["message_id"]
        response["tool_used"] = metadata["tool_used"]
        
        # Step 3: Generate TTS audio via external service
        if tts_client and ai_response:
            try:
                logger.info(f"🎵 Generating speech via external TTS")
                
                audio_response = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice="default",
                    speed=1.0,
                    language="EN"
                )
                
                if audio_response:
                    response["response_audio"] = base64.b64encode(audio_response).decode('utf-8')
                    response["has_audio"] = True
                    logger.info(f"✅ External TTS success: {len(audio_response)} bytes")
                    
            except Exception as tts_error:
                response["warnings"].append(f"TTS failed: {tts_error}")
                logger.error(f"❌ External TTS failed: {tts_error}")
        
        # Calculate total processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        response["processing_time"] = processing_time
        response["processing_complete"] = True
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Conversation processing failed: {e}", exc_info=True)
        
        response["errors"].append(f"Processing failed: {str(e)}")
        response["response_text"] = "I apologize, but I encountered an error. Please try again."
        response["processing_time"] = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return response

# NEW: Conversation history endpoint
@app.get("/v1/conversations")
async def get_conversations(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20
):
    """Get user's conversation history"""
    try:
        user = await conversation_orchestrator.conversation_manager.get_or_create_user(
            keycloak_id=current_user.uid,
            username=current_user.email or "unknown",
            email=current_user.email
        )
        
        conversations = await conversation_orchestrator.conversation_manager.get_user_conversations(
            user, limit
        )
        
        result = []
        for conv in conversations:
            result.append({
                "id": str(conv.id),
                "title": conv.title,
                "status": conv.status,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": conv.message_count,
                "summary": conv.summary
            })
        
        return {"conversations": result, "total": len(result)}
        
    except Exception as e:
        logger.error(f"Failed to get conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations")

# NEW: Tools endpoint
@app.get("/v1/tools")
async def get_available_tools(db: Session = Depends(get_db)):
    """Get available tools"""
    try:
        tools = await conversation_orchestrator.tool_system.get_available_tools()
        
        result = []
        for tool in tools:
            result.append({
                "name": tool.name,
                "display_name": tool.display_name,
                "description": tool.description,
                "category": tool.category,
                "schema": tool.schema
            })
        
        return {"tools": result}
        
    except Exception as e:
        logger.error(f"Failed to get tools: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve tools")

# Existing process_audio endpoint (backward compatibility)
@app.post("/v1/process-audio")
async def process_audio(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Existing audio processing endpoint for backward compatibility"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"🎤 Audio processing request from service: {calling_service}")
    
    # For now, return a simple response
    # In production, you might want to integrate this with the conversation system
    response = {
        "transcription": "Hello, this is the legacy endpoint",
        "transcription_confidence": 0.8,
        "response_text": "Please use the new /v1/conversation endpoint",
        "response_audio": None,
        "processed_by": "orchestrator",
        "caller": calling_service,
        "processing_complete": True
    }
    
    return response

# Media streaming event handler (existing)
@app.post("/v1/media/events")
async def handle_media_event(event: dict):
    """Handle events from media relay service"""
    try:
        event_type = event.get("type")
        session_id = event.get("session_id")
        
        logger.info(f"📥 Media event: {event_type} for session: {session_id}")
        
        # TODO: Integrate with conversation system
        return {"status": "received", "event_type": event_type}
        
    except Exception as e:
        logger.error(f"❌ Media event handling failed: {e}")
        return {"status": "error", "message": str(e)}

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize all service clients on startup"""
    global stt_client, tts_client, token_svc, service_auth
    
    # Initialize service authentication
    try:
        service_auth = create_service_auth_client("orchestrator")
        logger.info("✅ Service authentication initialized")
    except Exception as e:
        logger.warning(f"⚠️ Service authentication not available: {e}")
        service_auth = None
    
    if service_auth:
        # Initialize STT client
        if STT_SERVICE_URL:
            try:
                stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
                logger.info(f"✅ STT client configured: {STT_SERVICE_URL}")
            except Exception as e:
                logger.error(f"❌ STT client initialization failed: {e}")
        
        # Initialize External TTS client
        if EXTERNAL_TTS_URL:
            try:
                tts_client = ExternalTTSClient(EXTERNAL_TTS_URL, service_auth)
                logger.info(f"✅ External TTS client configured")
            except Exception as e:
                logger.error(f"❌ External TTS client initialization failed: {e}")
        
        # Initialize token service
        try:
            token_svc = TokenService(service_auth)
            global_token_service = token_svc
            logger.info("✅ Token service initialized")
        except Exception as e:
            logger.error(f"❌ Token service initialization failed: {e}")
    
    logger.info(f"""
    🚀 June Orchestrator v2.0 started:
    - Database: {'✅' if DATABASE_URL else '❌'}
    - STT: {'✅' if stt_client else '❌'} 
    - TTS: {'✅' if tts_client else '❌'} (External)
    - AI: {'✅' if ai_model else '❌'} ({'Gemini' if ai_model else 'fallback'})
    - Auth: {'✅' if service_auth else '❌'}
    - Conversations: {'✅' if conversation_orchestrator else '❌'}
    - Tools: {'✅' if conversation_orchestrator else '❌'}
    """)

# Include media streaming APIs
app.include_router(media_router)

# Keep existing generate_ai_response function for compatibility
async def generate_ai_response(user_input: str, user_context: dict = None) -> str:
    """Generate AI response using Gemini (legacy function)"""
    if not ai_model:
        return f"I received your message: '{user_input}'. This is a placeholder response."
    
    try:
        system_prompt = """You are June, a helpful AI assistant for life and house management. You are knowledgeable, friendly, and concise. 
        You help users with daily tasks, reminders, and managing their home life.
        
        Key traits:
        - Be helpful and practical
        - Focus on life and house management
        - Offer actionable suggestions
        - Be conversational and warm
        - If you don't know something, say so honestly
        """
        
        full_prompt = f"{system_prompt}\n\nUser: {user_input}\n\nJune:"
        
        response = ai_model.generate_content(full_prompt)
        
        if response.text:
            return response.text.strip()
        else:
            return "I'm having trouble generating a response right now. Could you try rephrasing your question?"
            
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        return f"I'm experiencing some technical difficulties, but I'm here to help you manage your life and house. What would you like assistance with?"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0", 
        port=int(os.getenv("PORT", "8080")),
        reload=False
    )