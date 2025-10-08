from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import logging
import asyncio
import uuid
from typing import Dict, Optional
from datetime import datetime

from .auth import verify_websocket_token, get_user_from_token
from .websocket_manager import ConnectionManager
from .services.ai_service import generate_ai_response
from .services.tts_service import synthesize_speech
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="June Orchestrator", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 June Orchestrator v2.0.0 - WebSocket-first architecture")

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator",
        "version": "2.0.0",
        "websocket_connections": len(manager.connections)
    }

@app.get("/status")
async def get_status():
    """Comprehensive service status"""
    return {
        "orchestrator": "healthy",
        "websocket_connections": len(manager.connections),
        "features": {
            "keycloak_authentication": True,
            "websocket_voice_chat": True,
            "real_time_ai": True,
            "tts_integration": True
        },
        "services": {
            "ai": bool(settings.gemini_api_key),
            "tts": settings.tts_base_url != "",
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """Main WebSocket endpoint for real-time voice chat"""
    
    # Authenticate WebSocket connection
    user = None
    if token:
        try:
            user = await verify_websocket_token(token)
            logger.info(f"WebSocket authenticated user: {user.get('sub', 'unknown')}")
        except Exception as e:
            logger.warning(f"WebSocket auth failed: {e}")
    
    session_id = await manager.connect(websocket, user)
    
    try:
        # Send connection confirmation
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": user is not None,
            "message": f"Connected to June AI Assistant as {user_id}",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Main message loop
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await process_websocket_message(message, session_id, user)
            
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
        logger.info(f"WebSocket client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {session_id}: {e}")
        await manager.disconnect(session_id)

async def process_websocket_message(message: dict, session_id: str, user: dict):
    """Process incoming WebSocket messages"""
    msg_type = message.get("type", "unknown")
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    logger.info(f"Processing {msg_type} from {user_id}")
    
    try:
        if msg_type == "text_input":
            await handle_text_input(message, session_id, user)
        elif msg_type == "audio_input":
            await handle_audio_input(message, session_id, user)
        elif msg_type == "ping":
            await manager.send_message(session_id, {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })
        else:
            await manager.send_message(session_id, {
                "type": "error", 
                "message": f"Unknown message type: {msg_type}",
                "timestamp": datetime.utcnow().isoformat()
            })
    except Exception as e:
        logger.error(f"Error processing {msg_type}: {e}")
        await manager.send_message(session_id, {
            "type": "error",
            "message": "Failed to process message",
            "timestamp": datetime.utcnow().isoformat()
        })

async def handle_text_input(message: dict, session_id: str, user: dict):
    """Handle text input from user"""
    text = message.get("text", "").strip()
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    if not text:
        await manager.send_message(session_id, {
            "type": "error",
            "message": "Empty text input",
            "timestamp": datetime.utcnow().isoformat()
        })
        return
    
    try:
        # Send processing status
        await manager.send_message(session_id, {
            "type": "processing_status",
            "status": "thinking", 
            "message": "Generating AI response...",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate AI response
        ai_response = await generate_ai_response(text, user_id)
        
        # Send text response
        await manager.send_message(session_id, {
            "type": "text_response",
            "text": ai_response,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate TTS audio
        await manager.send_message(session_id, {
            "type": "processing_status",
            "status": "generating_audio",
            "message": "Converting to speech...",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        audio_data = await synthesize_speech(ai_response)
        if audio_data:
            await manager.send_message(session_id, {
                "type": "audio_response", 
                "audio_data": audio_data,
                "text": ai_response,
                "content_type": "audio/wav",
                "timestamp": datetime.utcnow().isoformat()
            })
        else:
            await manager.send_message(session_id, {
                "type": "warning",
                "message": "Text-to-speech failed. Response sent as text only.",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Send completion status
        await manager.send_message(session_id, {
            "type": "processing_complete",
            "timestamp": datetime.utcnow().isoformat()
        })
            
    except Exception as e:
        logger.error(f"Error processing text input: {e}")
        await manager.send_message(session_id, {
            "type": "error",
            "message": "Failed to process text input",
            "timestamp": datetime.utcnow().isoformat()
        })

async def handle_audio_input(message: dict, session_id: str, user: dict):
    """Handle audio input from user"""
    await manager.send_message(session_id, {
        "type": "info",
        "message": "Audio processing not yet implemented. Please use text input or STT service directly.",
        "timestamp": datetime.utcnow().isoformat()
    })

# STT Webhook (for backward compatibility)
@app.post("/v1/stt/webhook")
async def stt_webhook(request: dict):
    """Process STT webhook results"""
    try:
        user_id = request.get('user_id', 'webhook_user')
        transcript = request.get('transcript', '')
        session_id = request.get('session_id')
        
        logger.info(f"STT webhook: {transcript[:50]}... from {user_id}")
        
        # If we have a session_id, try to send via WebSocket
        if session_id and session_id in manager.connections:
            await manager.send_message(session_id, {
                "type": "transcript",
                "text": transcript,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Process as text input
            user = manager.get_user(session_id)
            await handle_text_input({"text": transcript}, session_id, user)
        
        return {
            "status": "processed",
            "user_id": user_id,
            "transcript_length": len(transcript),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"STT webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)