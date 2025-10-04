# June/services/june-orchestrator/app.py
# SIMPLIFIED AND CLEAR VERSION

import os
import time
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Authentication
try:
    from shared.auth import get_auth_service, AuthError
    SHARED_AUTH_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Shared auth module loaded")
except ImportError:
    SHARED_AUTH_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Shared auth module not available, authentication will be disabled")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Gemini imports
USING_NEW_SDK = False
try:
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
    logger.info("✅ Using new Google GenAI SDK")
except ImportError:
    try:
        import google.generativeai as genai
        USING_NEW_SDK = False
        logger.info("✅ Using legacy google-generativeai library")
    except ImportError:
        logger.error("❌ No Gemini library found")
        genai = None

from tts_client import get_tts_client

app = FastAPI(
    title="June Orchestrator", 
    version="4.0.0", 
    description="June AI Platform Orchestrator - Clear Logic"
)

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ==========================================
# DATA MODELS - CLEAR AND SIMPLE
# ==========================================

class AudioConfig(BaseModel):
    """Audio configuration for TTS"""
    voice: Optional[str] = Field(default="default")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    language: Optional[str] = Field(default="EN")

class ChatRequest(BaseModel):
    """Direct chat request from frontend (user types text)"""
    text: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1000, ge=1, le=4000)
    include_audio: Optional[bool] = Field(default=False)
    audio_config: Optional[AudioConfig] = Field(default=None)

class TranscriptFromSTT(BaseModel):
    """What STT sends to orchestrator after transcribing user's speech"""
    transcript_id: str
    user_id: str
    text: str  # THIS IS WHAT THE USER SAID
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    metadata: Dict[str, Any] = {}

class ChatResponse(BaseModel):
    """AI response sent back to frontend"""
    ok: bool
    message: Dict[str, str]  # {"text": "AI's response", "role": "assistant"}
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"
    audio: Optional[Dict] = Field(default=None)

# ==========================================
# STORAGE
# ==========================================

# Store transcripts we receive from STT
user_conversations = {}  # user_id -> list of messages

# ==========================================
# GEMINI SERVICE
# ==========================================

class GeminiService:
    def __init__(self):
        self.model = None
        self.client = None
        self.api_key = None
        self.is_available = False
        self.initialize()
    
    def initialize(self):
        try:
            self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
            
            if not self.api_key or len(self.api_key) < 30:
                logger.warning("❌ GEMINI_API_KEY not set or invalid")
                return False
            
            if not genai:
                logger.warning("❌ No Gemini library available")
                return False
            
            logger.info(f"🔧 Initializing Gemini with API key: {self.api_key[:10]}...")
            
            if USING_NEW_SDK:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ New GenAI SDK configured")
                
                try:
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash', 
                        contents='Hello, are you working?'
                    )
                    if response and response.text:
                        logger.info(f"✅ Gemini test successful")
                        self.is_available = True
                        return True
                except Exception as e:
                    logger.warning(f"❌ Gemini test failed: {e}")
                    return False
            else:
                genai.configure(api_key=self.api_key)
                try:
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    test_response = self.model.generate_content("Hello")
                    if test_response and test_response.text:
                        logger.info(f"✅ Legacy SDK test successful")
                        self.is_available = True
                        return True
                except Exception as e:
                    logger.error(f"❌ Legacy SDK test failed: {e}")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            return False
    
    async def process_user_message(self, text: str, language: str = "en", user_id: str = "unknown") -> str:
        """
        CORE FUNCTION: Process what the user said and generate AI response
        
        Args:
            text: What the user said (from STT or typed)
            language: Language of conversation
            user_id: Who is speaking
            
        Returns:
            AI's response text
        """
        if not self.is_available:
            logger.warning("❌ Gemini not available, using fallback")
            return self._get_fallback_response(text, language)
        
        try:
            # Get conversation history for context
            history = user_conversations.get(user_id, [])
            
            # Build context-aware prompt
            system_prompts = {
                "en": "You are JUNE, a helpful AI assistant. You're having a natural conversation with a user who is speaking to you.",
                "es": "Eres JUNE, un asistente de IA útil. Estás teniendo una conversación natural con un usuario que te está hablando.",
            }
            
            system_prompt = system_prompts.get(language, system_prompts["en"])
            
            # Include recent history for context (last 5 messages)
            context = ""
            if history:
                recent = history[-5:]
                context = "\n".join([f"{msg['role']}: {msg['text']}" for msg in recent])
                context += f"\n\nUser: {text}\n\nAssistant:"
            else:
                context = f"User: {text}\n\nAssistant:"
            
            full_prompt = f"{system_prompt}\n\n{context}"
            
            logger.info(f"🤖 Processing message from user {user_id}: {text[:50]}...")
            
            if USING_NEW_SDK and self.client:
                response = self.client.models.generate_content(
                    model='gemini-1.5-flash',
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7, 
                        max_output_tokens=1000
                    )
                )
                
                if response and response.text:
                    ai_text = response.text.strip()
                    logger.info(f"✅ AI response generated: {ai_text[:100]}...")
                    
                    # Store in conversation history
                    if user_id not in user_conversations:
                        user_conversations[user_id] = []
                    
                    user_conversations[user_id].append({
                        "role": "user",
                        "text": text,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    user_conversations[user_id].append({
                        "role": "assistant",
                        "text": ai_text,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                    # Keep only last 20 messages
                    if len(user_conversations[user_id]) > 20:
                        user_conversations[user_id] = user_conversations[user_id][-20:]
                    
                    return ai_text
            else:
                if self.model:
                    generation_config = genai.types.GenerationConfig(
                        temperature=0.7, 
                        max_output_tokens=1000
                    )
                    response = self.model.generate_content(
                        full_prompt, 
                        generation_config=generation_config
                    )
                    
                    if response and response.text:
                        ai_text = response.text.strip()
                        logger.info(f"✅ AI response: {ai_text[:100]}...")
                        return ai_text
            
            logger.error("❌ No response from Gemini")
            return self._get_fallback_response(text, language)
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return self._get_fallback_response(text, language)
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        """Fallback response when AI is unavailable"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hello", "hi", "hey"]):
            return "Hello! I'm JUNE, your AI assistant. How can I help you today?"
        
        if any(word in text_lower for word in ["thank", "thanks"]):
            return "You're welcome! Is there anything else I can help you with?"
        
        return f"I heard you say: '{text}'. I'm currently in basic mode, but I'm here to help!"

gemini_service = GeminiService()

# ==========================================
# AUTHENTICATION
# ==========================================

async def verify_service_token(authorization: str = None) -> Dict[str, Any]:
    """Verify service-to-service token (for STT calling orchestrator)"""
    # Simple token check for service-to-service
    SERVICE_TOKEN = os.getenv("STT_SERVICE_TOKEN", "stt-service-secret-token-2025")
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization.replace("Bearer ", "").strip()
    
    if token == SERVICE_TOKEN:
        logger.info("✅ Service authenticated: june-stt")
        return {
            "service": "june-stt",
            "authenticated": True,
            "type": "service_to_service"
        }
    
    raise HTTPException(status_code=401, detail="Invalid service token")

async def verify_user_token(authorization: str = None) -> Dict[str, Any]:
    """Verify user authentication token from frontend"""
    if not SHARED_AUTH_AVAILABLE:
        logger.warning("⚠️ Authentication disabled - shared auth not available")
        return {"sub": "anonymous", "authenticated": False}
    
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing authorization")
        
        token = authorization.replace("Bearer ", "").strip()
        
        auth_service = get_auth_service()
        token_data = await auth_service.verify_bearer(token)
        
        user_id = token_data.get('sub', 'unknown')
        logger.info(f"✅ User authenticated: {user_id}")
        return token_data
        
    except AuthError as e:
        logger.error(f"❌ User authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")

# ==========================================
# ENDPOINTS - CLEAR LOGIC
# ==========================================

@app.get("/")
async def root():
    """Service info"""
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    
    return {
        "service": "June Orchestrator",
        "version": "4.0.0 - Clear Logic",
        "status": "healthy",
        "features": {
            "ai_chat": gemini_service.is_available, 
            "text_to_speech": tts_status.get("available", False),
            "speech_to_text_integration": True,
            "conversation_memory": True
        },
        "flow": {
            "1": "User speaks → STT transcribes",
            "2": "STT sends transcript → Orchestrator (this service)",
            "3": "Orchestrator processes with AI",
            "4": "Orchestrator responds → Frontend"
        },
        "endpoints": {
            "health": "/healthz",
            "user_chat_typed": "/v1/chat",
            "stt_webhook": "/v1/stt/webhook",
            "conversation_history": "/v1/conversations/{user_id}"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator", 
        "version": "4.0.0",
        "timestamp": time.time(),
        "ai_available": gemini_service.is_available
    }

# ==========================================
# ENDPOINT 1: USER TYPES TEXT (Direct chat)
# ==========================================

@app.post("/v1/chat", response_model=ChatResponse)
async def chat_typed(
    request: ChatRequest,
    authorization: str = None
):
    """
    USER TYPES TEXT directly in the app
    
    Flow:
    1. User types message in frontend
    2. Frontend sends text here
    3. We process with AI
    4. Return response (+ optional TTS audio)
    """
    start_time = time.time()
    
    try:
        # Authenticate user (optional for now)
        user_id = "anonymous"
        if authorization:
            try:
                user_auth = await verify_user_token(authorization)
                user_id = user_auth.get("sub", "anonymous")
            except:
                pass
        
        logger.info(f"💬 User {user_id} typed: {request.text[:50]}...")
        
        # Process with AI
        ai_response = await gemini_service.process_user_message(
            text=request.text.strip(),
            language=request.language,
            user_id=user_id
        )
        
        response_time = int((time.time() - start_time) * 1000)
        
        chat_response = ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{user_id}-{int(time.time())}",
            ai_provider="gemini" if gemini_service.is_available else "fallback"
        )
        
        # Add TTS audio if requested
        if request.include_audio:
            try:
                logger.info("🔊 Generating TTS audio for response...")
                tts_client = get_tts_client()
                audio_config = request.audio_config or AudioConfig()
                
                audio_result = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice=audio_config.voice,
                    speed=audio_config.speed,
                    language=audio_config.language,
                    reference_audio_b64=None
                )
                
                audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                
                chat_response.audio = {
                    "data": audio_b64,
                    "content_type": audio_result["content_type"],
                    "size_bytes": audio_result["size_bytes"],
                    "voice": audio_result["voice"],
                    "speed": audio_result["speed"],
                    "language": audio_result["language"]
                }
                
                logger.info(f"✅ TTS audio generated: {audio_result['size_bytes']} bytes")
                
            except Exception as e:
                logger.error(f"❌ TTS generation failed: {e}")
        
        logger.info(f"✅ Response sent to user {user_id} ({response_time}ms)")
        return chat_response
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"I apologize, but I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

# ==========================================
# ENDPOINT 2: STT SENDS TRANSCRIPT (User spoke)
# ==========================================

@app.post("/v1/stt/webhook")
async def receive_transcript_from_stt(
    transcript: TranscriptFromSTT,
    background_tasks: BackgroundTasks,
    authorization: str = None
):
    """
    STT SERVICE SENDS TRANSCRIPT here after user speaks
    
    Flow:
    1. User speaks into app
    2. Frontend sends audio to STT
    3. STT transcribes audio → text
    4. STT calls THIS endpoint with the text
    5. We process with AI and send response back
    
    This is the KEY endpoint for voice interaction!
    """
    start_time = time.time()
    
    try:
        # Verify this is really STT calling us
        service_auth = await verify_service_token(authorization)
        
        logger.info("="*70)
        logger.info(f"🎙️ RECEIVED TRANSCRIPT FROM STT")
        logger.info(f"   Transcript ID: {transcript.transcript_id}")
        logger.info(f"   User ID: {transcript.user_id}")
        logger.info(f"   User said: '{transcript.text}'")
        logger.info(f"   Language: {transcript.language}")
        logger.info(f"   Confidence: {transcript.confidence}")
        logger.info("="*70)
        
        # THIS IS WHAT THE USER SAID - Now process with AI
        user_message = transcript.text
        user_id = transcript.user_id
        language = transcript.language or "en"
        
        # Process with AI
        ai_response = await gemini_service.process_user_message(
            text=user_message,
            language=language,
            user_id=user_id
        )
        
        logger.info(f"🤖 AI Response: '{ai_response[:100]}...'")
        
        # TODO: Send AI response back to frontend via WebSocket or push notification
        # For now, just store it - frontend will poll /v1/conversations/{user_id}
        
        response_time = int((time.time() - start_time) * 1000)
        
        return {
            "status": "success",
            "transcript_id": transcript.transcript_id,
            "user_id": user_id,
            "user_said": user_message,
            "ai_response": ai_response,
            "processing_time_ms": response_time,
            "message": "Transcript received and processed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing STT transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# ENDPOINT 3: GET CONVERSATION HISTORY
# ==========================================

@app.get("/v1/conversations/{user_id}")
async def get_conversation(
    user_id: str,
    authorization: str = None,
    limit: int = 20
):
    """
    Get conversation history for a user
    
    Frontend can poll this to get latest messages
    """
    try:
        # Authenticate
        if authorization:
            user_auth = await verify_user_token(authorization)
            authenticated_user_id = user_auth.get("sub")
            
            # Users can only see their own conversations
            if authenticated_user_id != user_id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Get conversation
        messages = user_conversations.get(user_id, [])
        
        # Return latest messages
        latest = messages[-limit:] if len(messages) > limit else messages
        
        return {
            "user_id": user_id,
            "total_messages": len(messages),
            "messages": latest,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# TTS STATUS
# ==========================================

@app.get("/v1/tts/status")
async def tts_status():
    """Check if TTS is available"""
    tts_client = get_tts_client()
    return await tts_client.get_status()

# ==========================================
# STARTUP
# ==========================================

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v4.0.0 - Clear Logic")
    logger.info("="*70)
    logger.info("FLOW:")
    logger.info("1. User speaks → STT transcribes")
    logger.info("2. STT sends transcript → /v1/stt/webhook")
    logger.info("3. Orchestrator processes with AI")
    logger.info("4. Orchestrator stores response")
    logger.info("5. Frontend polls /v1/conversations/{user_id} for response")
    logger.info("="*70)
    
    if gemini_service.is_available:
        logger.info("✅ Gemini AI service ready")
    else:
        logger.warning("⚠️ Gemini AI service not ready - using fallback responses")
    
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    if tts_status.get("available", False):
        logger.info("✅ TTS service ready")
    else:
        logger.warning("⚠️ TTS service not reachable")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")