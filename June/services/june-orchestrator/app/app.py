import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Import your existing services
from app.auth import get_current_user, get_anonymous_user
from app.ai_service import get_ai_service, AIService
from app.tts_client import get_tts_client
from app.stt_client import get_stt_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June Orchestrator",
    description="AI Voice Chat Orchestrator with WebSocket Support",
    version="6.0.0"
)

# CORS configuration for your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://allsafe.world"],  # Add your frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
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
            await self.active_connections[session_id].send_text(json.dumps(message))

manager = ConnectionManager()

# Pydantic models
class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = "anonymous"

class AudioMessage(BaseModel):
    type: str
    audio_data: Optional[str] = None
    text: Optional[str] = None
    user_id: Optional[str] = "anonymous"

# Health check endpoints
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "june-orchestrator", "version": "6.0.0"}

@app.get("/status")
async def get_status():
    """Get status of all services"""
    ai_service = get_ai_service()
    tts_client = get_tts_client()
    stt_client = get_stt_client()
    
    # Check AI service
    ai_available = ai_service.is_available()
    
    # Check TTS service
    tts_status = await tts_client.get_status()
    tts_available = tts_status.get("available", False)
    
    # Check STT service (if you have health check)
    stt_available = True  # Add STT health check if available
    
    return {
        "orchestrator": "healthy",
        "ai_service": {"available": ai_available, "provider": "gemini" if ai_available else "none"},
        "tts_service": tts_status,
        "stt_service": {"available": stt_available},
        "websocket_connections": len(manager.active_connections),
        "timestamp": datetime.utcnow().isoformat()
    }

# WebSocket voice chat endpoint
@app.websocket("/ws/voice-chat")
async def websocket_voice_chat(websocket: WebSocket):
    session_id = str(uuid.uuid4())
    user_id = "anonymous"  # You can implement auth here
    
    await manager.connect(websocket, session_id, user_id)
    
    # Send welcome message
    await manager.send_personal_message({
        "type": "connection_established",
        "session_id": session_id,
        "message": "Connected to June AI Assistant",
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
    
    # Convert audio to text using STT service
    try:
        audio_bytes = base64.b64decode(audio_data)
        stt_client = get_stt_client()
        transcript_result = await stt_client.transcribe_audio(audio_bytes)
        transcript = transcript_result.get("transcript", "").strip()
        
        if not transcript:
            await manager.send_personal_message({
                "type": "error",
                "message": "Could not transcribe audio. Please try again.",
                "timestamp": datetime.utcnow().isoformat()
            }, session_id)
            return
            
        logger.info(f"🎙️ Transcript from {user_id}: {transcript}")
        
        # Send transcript to user
        await manager.send_personal_message({
            "type": "transcript",
            "text": transcript,
            "user": user_id,
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)
        
    except Exception as e:
        logger.error(f"❌ STT failed: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": "Speech recognition failed. Please try again.",
            "timestamp": datetime.utcnow().isoformat()
        }, session_id)
        return
    
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
        if ai_service.is_available():
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
            logger.info(f"🔊 TTS generated for {user_id} ({len(tts_result['audio_data'])} chars base64)")
            
            # Send audio response
            await manager.send_personal_message({
                "type": "audio_response",
                "audio_data": tts_result["audio_data"],
                "text": ai_response,
                "speaker": tts_result.get("voice", "default"),
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

# Legacy HTTP endpoints (keeping for backward compatibility)
@app.post("/v1/chat")
async def chat(request: ChatRequest):
    """Legacy HTTP chat endpoint"""
    try:
        ai_service = get_ai_service()
        if ai_service.is_available():
            response = await ai_service.generate_response(request.message, request.user_id)
        else:
            response = f"I received your message: '{request.message[:50]}...' Please use WebSocket for full voice features."
        
        return {
            "response": response,
            "user_id": request.user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Use WebSocket /ws/voice-chat for real-time voice features"
        }
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
