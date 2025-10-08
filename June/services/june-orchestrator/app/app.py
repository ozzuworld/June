import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, List
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Your existing imports
from app.auth import authenticate_user, get_user_by_token, create_access_token, verify_token
from app.ai_service import get_ai_service, AIService
from app.tts_client import get_tts_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June Orchestrator", 
    description="Advanced AI Voice Chat Orchestrator with Real-time WebSocket Support",
    version="6.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager (NEW FEATURE)
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_sessions: Dict[str, str] = {}  # session_id -> user_id

    async def connect(self, websocket: WebSocket, session_id: str, user_id: str = "anonymous"):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.user_sessions[session_id] = user_id
        logger.info(f"🔌 WebSocket connected: {session_id} (user: {user_id})")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        if session_id in self.user_sessions:
            del self.user_sessions[session_id]
        logger.info(f"🔌 WebSocket disconnected: {session_id}")

    async def send_personal_message(self, message: dict, session_id: str):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send message to {session_id}: {e}")
                self.disconnect(session_id)

manager = ConnectionManager()

# Your existing models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = "anonymous"

class STTWebhookRequest(BaseModel):
    transcript: str
    user_id: str
    session_id: Optional[str] = None
    confidence: Optional[float] = None

class TTSRequest(BaseModel):
    text: str
    user_id: Optional[str] = "anonymous"
    voice: str = "default"
    language: str = "en"
    speed: float = 1.0

# NEW WebSocket models
class AudioMessage(BaseModel):
    type: str
    audio_data: Optional[str] = None
    text: Optional[str] = None
    user_id: Optional[str] = "anonymous"

# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v6.0.0")
    
    # Check AI service availability
    ai_service = get_ai_service()
    ai_available = ai_service.is_available() if ai_service else False
    logger.info(f"AI Available: {ai_available}")
    
    # Check TTS service availability
    try:
        tts_client = get_tts_client()
        tts_status = await tts_client.get_status()
        tts_available = tts_status.get("available", False)
        logger.info(f"TTS Available: {tts_available}")
    except Exception as e:
        logger.warning(f"⚠️ TTS service check failed: {e}")
        
    logger.info("✅ Orchestrator ready with WebSocket support")

# Health endpoints
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "june-orchestrator", "version": "6.0.0"}

@app.get("/status")
async def get_status():
    """Get comprehensive service status"""
    ai_service = get_ai_service()
    tts_client = get_tts_client()
    
    # Check AI service
    ai_available = ai_service.is_available() if ai_service else False
    
    # Check TTS service
    try:
        tts_status = await tts_client.get_status()
        tts_available = tts_status.get("available", False)
    except Exception as e:
        tts_available = False
        tts_status = {"available": False, "error": str(e)}
    
    return {
        "orchestrator": "healthy",
        "ai_service": {
            "available": ai_available, 
            "provider": "gemini" if ai_available else "none"
        },
        "tts_service": tts_status,
        "stt_service": {"available": True},  # Assuming available
        "websocket_connections": len(manager.active_connections),
        "features": {
            "authentication": True,
            "websocket_voice_chat": True,
            "http_api": True,
            "stt_webhook": True
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# Your existing authentication endpoints
@app.post("/v1/auth/register")
async def register(user: UserCreate):
    try:
        # Your existing registration logic
        new_user = await authenticate_user(user.username, user.password, create=True, email=user.email)
        if new_user:
            access_token = create_access_token(data={"sub": user.username})
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user": {
                    "username": user.username,
                    "email": user.email
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Registration failed")
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/auth/login")
async def login(user: UserLogin):
    try:
        authenticated_user = await authenticate_user(user.username, user.password)
        if authenticated_user:
            access_token = create_access_token(data={"sub": user.username})
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user": authenticated_user
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Your existing chat endpoint
@app.post("/v1/chat")
async def chat(request: ChatRequest):
    """Enhanced HTTP chat endpoint"""
    try:
        start_time = time.time()
        
        # Get user info (if available)
        user_info = "anonymous"
        try:
            if request.user_id and request.user_id != "anonymous":
                user_info = request.user_id
        except:
            pass
            
        logger.info(f"💬 Chat from {user_info}: {request.message[:50]}...")
        
        # Generate AI response
        ai_service = get_ai_service()
        if ai_service and ai_service.is_available():
            response = await ai_service.generate_response(request.message, request.user_id)
        else:
            response = f"I received your message: '{request.message[:50]}...' I'm currently in basic mode."
        
        processing_time = int((time.time() - start_time) * 1000)
        logger.info(f"✅ Chat response sent to {user_info} ({processing_time}ms)")
        
        return {
            "response": response,
            "user_id": request.user_id,
            "processing_time_ms": processing_time,
            "timestamp": datetime.utcnow().isoformat(),
            "websocket_available": True
        }
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Your existing STT webhook
@app.post("/v1/stt/webhook")
async def stt_webhook(request: dict):
    """Process STT webhook and generate TTS response"""
    start_time = time.time()
    
    try:
        user_id = request.get('user_id', 'fallback_user')
        transcript_text = request.get('transcript', '')
        session_id = request.get('session_id', str(uuid.uuid4()))
        
        logger.info(f"🎙️ Transcript from {user_id}: {transcript_text}")
        
        # Generate AI response
        ai_service = get_ai_service()
        if ai_service and ai_service.is_available():
            response_text = await ai_service.generate_response(transcript_text, user_id)
        else:
            response_text = f"I received your message: '{transcript_text[:50]}...' I'm currently in basic mode."
        
        logger.info(f"🔊 Generating TTS audio for response: {response_text[:50]}...")
        
        # Generate TTS audio
        try:
            tts_client = get_tts_client()
            tts_result = await tts_client.synthesize_speech(
                text=response_text,
                language="en",
                voice="Claribel Dervla",
                speed=1.0
            )
            
            if "audio_data" in tts_result:
                logger.info(f"✅ TTS audio generated successfully")
                # Here you can save the audio file or send it to your frontend
                # For now, we'll just log success
            else:
                logger.warning(f"⚠️ TTS failed: {tts_result.get('error', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"❌ TTS generation failed: {e}")
        
        processing_time = int((time.time() - start_time) * 1000)
        logger.info(f"✅ Processed transcript {session_id[:8]}... ({processing_time}ms)")
        
        return {
            "response": response_text,
            "user_id": user_id,
            "session_id": session_id,
            "processing_time_ms": processing_time,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ STT webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Your existing TTS endpoint
@app.post("/v1/tts/generate")
async def generate_tts(request: TTSRequest):
    """Generate TTS audio"""
    try:
        logger.info(f"🔊 TTS request from {request.user_id}: {request.text[:50]}...")
        
        tts_client = get_tts_client()
        result = await tts_client.synthesize_speech(
            text=request.text,
            language=request.language,
            voice=request.voice,
            speed=request.speed
        )
        
        if "audio_data" in result:
            return {
                "audio_data": result["audio_data"],
                "content_type": result.get("content_type", "audio/wav"),
                "size_bytes": result.get("size_bytes", 0),
                "user_id": request.user_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "TTS generation failed"))
            
    except Exception as e:
        logger.error(f"❌ TTS generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# NEW WebSocket endpoint for real-time voice chat
@app.websocket("/ws/voice-chat")
async def websocket_voice_chat(websocket: WebSocket):
    session_id = str(uuid.uuid4())
    user_id = "anonymous"  # Can be enhanced with auth token
    
    await manager.connect(websocket, session_id, user_id)
    
    # Send welcome message
    await manager.send_personal_message({
        "type": "connection_established",
        "session_id": session_id,
        "message": "Connected to June AI Assistant",
        "features": ["voice_input", "text_input", "audio_output", "real_time"],
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    try:
        while True:
            # Receive message from frontend
            data = await websocket.receive_text()
            message = json.loads(data)
            
            await process_websocket_message(message, session_id, user_id)
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)
        logger.info(f"🔌 Client {session_id} disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error for {session_id}: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": f"An error occurred: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)
        manager.disconnect(session_id)

async def process_websocket_message(message: dict, session_id: str, user_id: str):
    """Process incoming WebSocket messages"""
    message_type = message.get("type", "unknown")
    start_time = time.time()
    
    try:
        if message_type == "audio_input":
            await process_audio_input(message, session_id, user_id, start_time)
        elif message_type == "text_input":
            await process_text_input(message, session_id, user_id, start_time)
        elif message_type == "ping":
            await manager.send_personal_message({
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            }, session_id)
        else:
            logger.warning(f"⚠️ Unknown message type: {message_type}")
            await manager.send_personal_message({
                "type": "error",
                "message": f"Unknown message type: {message_type}",
                "timestamp": datetime.utcnow().isoformat()
            }, session_id)
            
    except Exception as e:
        logger.error(f"❌ Error processing {message_type}: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": f"Failed to process {message_type}: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)

async def process_audio_input(message: dict, session_id: str, user_id: str, start_time: float):
    """Process audio input from user"""
    audio_data = message.get("audio_data")
    if not audio_data:
        raise ValueError("No audio data provided")
    
    logger.info(f"🎙️ Processing audio from {user_id} (session: {session_id[:8]}...)")
    
    # Send status update
    await manager.send_personal_message({
        "type": "processing_status",
        "status": "transcribing",
        "message": "Converting speech to text...",
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    # For now, simulate STT - you can integrate your STT service here
    # TODO: Add STT service integration
    transcript = "This is a simulated transcript from your audio input"
    
    logger.info(f"🎙️ Transcript from {user_id}: {transcript}")
    
    # Send transcript to user
    await manager.send_personal_message({
        "type": "transcript",
        "text": transcript,
        "user": user_id,
        "confidence": 0.95,
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    # Process the transcript as text
    await process_text_message(transcript, session_id, user_id, start_time)

async def process_text_input(message: dict, session_id: str, user_id: str, start_time: float):
    """Process text input from user"""
    text = message.get("text", "").strip()
    if not text:
        raise ValueError("No text provided")
    
    await process_text_message(text, session_id, user_id, start_time)

async def process_text_message(text: str, session_id: str, user_id: str, start_time: float):
    """Process text message and generate AI response with TTS"""
    
    # Send thinking status
    await manager.send_personal_message({
        "type": "processing_status",
        "status": "thinking",
        "message": "Generating response...",
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    # Generate AI response
    try:
        ai_service = get_ai_service()
        if ai_service and ai_service.is_available():
            ai_response = await ai_service.generate_response(text, user_id)
        else:
            ai_response = f"I received your message: '{text[:50]}...' I'm currently in basic mode without AI capabilities."
            
        logger.info(f"🤖 AI response to {user_id}: {ai_response[:100]}...")
        
        # Send text response
        await manager.send_personal_message({
            "type": "text_response",
            "text": ai_response,
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)
        
    except Exception as e:
        logger.error(f"❌ AI generation failed: {e}")
        ai_response = "I'm having trouble generating a response right now. Please try again."
    
    # Send TTS status
    await manager.send_personal_message({
        "type": "processing_status",
        "status": "generating_audio",
        "message": "Converting text to speech...",
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    # Generate TTS audio
    try:
        tts_client = get_tts_client()
        tts_result = await tts_client.synthesize_speech(
            text=ai_response,
            language="en",
            voice="Claribel Dervla",
            speed=1.0
        )
        
        if "audio_data" in tts_result:
            logger.info(f"🔊 TTS generated for {user_id}")
            
            # Send audio response
            await manager.send_personal_message({
                "type": "audio_response",
                "audio_data": tts_result["audio_data"],
                "text": ai_response,
                "speaker": tts_result.get("voice", "default"),
                "content_type": tts_result.get("content_type", "audio/wav"),
                "timestamp": datetime.utcnow().isoformat()
            }, session_id)
            
        else:
            logger.warning(f"⚠️ TTS failed for {user_id}: {tts_result.get('error', 'Unknown error')}")
            await manager.send_personal_message({
                "type": "error",
                "message": "Text-to-speech failed. Response sent as text only.",
                "timestamp": datetime.utcnow().isoformat()
            }, session_id)
            
    except Exception as e:
        logger.error(f"❌ TTS failed: {e}")
        await manager.send_personal_message({
            "type": "error", 
            "message": "Text-to-speech failed. Response sent as text only.",
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)
    
    # Send completion status
    processing_time = int((time.time() - start_time) * 1000)
    await manager.send_personal_message({
        "type": "processing_complete",
        "processing_time_ms": processing_time,
        "timestamp": datetime.utcnow().isoformat()
    }, session_id)
    
    logger.info(f"✅ Processed message for {user_id} ({processing_time}ms)")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
