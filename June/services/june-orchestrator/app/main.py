"""
June Orchestrator - Complete main.py with Fixed WebSocket Authentication
Supports both query parameter and header-based authentication
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Query
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

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "2.0.0",
        "status": "running",
        "websocket": "ws://host/ws or wss://host/ws",
        "auth_methods": ["header: Authorization: Bearer <token>", "query: ?token=<token>"]
    }

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
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),  # Support token in query parameter
    authorization: Optional[str] = Header(None)  # Support token in Authorization header
):
    """
    Main WebSocket endpoint for real-time voice chat
    
    Authentication methods supported:
    1. Authorization header: ws.connect(url, headers: {'Authorization': 'Bearer <token>'})
    2. Query parameter: ws.connect(url + '?token=<token>')
    
    The token can be passed with or without 'Bearer ' prefix.
    """
    
    # Extract authentication token from either source
    auth_token = None
    auth_method = None
    
    if authorization:
        # Prefer Authorization header (more secure, standard method)
        auth_token = authorization.replace('Bearer ', '').replace('Bearer%20', '').strip()
        auth_method = "header"
        logger.info("🔑 Token received via Authorization header")
    elif token:
        # Fallback to query parameter (for clients that can't set headers)
        auth_token = token.replace('Bearer ', '').replace('Bearer%20', '').strip()
        auth_method = "query"
        logger.info("🔑 Token received via query parameter")
    else:
        logger.warning("⚠️ No authentication token provided")
    
    # Authenticate the connection
    user = None
    if auth_token:
        try:
            user = await verify_websocket_token(auth_token)
            user_id = user.get("sub", "unknown")
            logger.info(f"✅ WebSocket authenticated: {user_id} (via {auth_method})")
        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            # Close connection before accepting if auth fails
            await websocket.close(code=1008, reason="Authentication failed")
            return
    else:
        logger.warning("⚠️ Allowing unauthenticated WebSocket connection (development mode)")
        # For production, uncomment this to require authentication:
        # await websocket.close(code=1008, reason="Authentication required")
        # return
    
    # ✅ CRITICAL: Accept WebSocket connection AFTER successful authentication
    await websocket.accept()
    
    # Register the connection with the manager
    session_id = await manager.connect(websocket, user)
    
    try:
        # Send connection confirmation with detailed info
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        user_email = user.get("email", "N/A") if user else "N/A"
        
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "email": user_email,
            "session_id": session_id,
            "authenticated": user is not None,
            "auth_method": auth_method,
            "message": f"✅ Connected to June AI Assistant as {user_id}",
            "server_time": datetime.utcnow().isoformat(),
            "available_commands": [
                {"type": "text_input", "description": "Send text message to AI"},
                {"type": "audio_input", "description": "Send audio for transcription"},
                {"type": "ping", "description": "Keep connection alive"}
            ]
        })
        
        logger.info(f"🔌 WebSocket session established: {session_id} for user: {user_id}")
        
        # Main message loop
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Process the message
            await process_websocket_message(message, session_id, user)
            
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
        logger.info(f"🔌 WebSocket client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"❌ WebSocket error for {session_id}: {e}", exc_info=True)
        await manager.disconnect(session_id)


async def process_websocket_message(message: dict, session_id: str, user: dict):
    """Process incoming WebSocket messages"""
    msg_type = message.get("type", "unknown")
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    logger.info(f"📨 Processing message type '{msg_type}' from user {user_id}")
    
    try:
        if msg_type == "text_input":
            await handle_text_input(message, session_id, user)
        
        elif msg_type == "audio_input":
            await handle_audio_input(message, session_id, user)
        
        elif msg_type == "ping":
            # Simple keep-alive mechanism
            await manager.send_message(session_id, {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif msg_type == "get_status":
            # Client requesting connection status
            await manager.send_message(session_id, {
                "type": "status",
                "session_id": session_id,
                "user_id": user_id,
                "authenticated": user is not None,
                "connected_since": datetime.utcnow().isoformat(),
                "server_status": "healthy"
            })
        
        else:
            # Unknown message type
            await manager.send_message(session_id, {
                "type": "error", 
                "message": f"Unknown message type: {msg_type}",
                "supported_types": ["text_input", "audio_input", "ping", "get_status"],
                "timestamp": datetime.utcnow().isoformat()
            })
    
    except Exception as e:
        logger.error(f"❌ Error processing {msg_type}: {e}", exc_info=True)
        await manager.send_message(session_id, {
            "type": "error",
            "message": "Failed to process message",
            "error_type": type(e).__name__,
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
    
    logger.info(f"💬 Text input from {user_id}: {text[:50]}...")
    
    try:
        # Send processing status
        await manager.send_message(session_id, {
            "type": "processing_status",
            "status": "thinking", 
            "message": "🤔 Generating AI response...",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate AI response
        ai_response = await generate_ai_response(text, user_id)
        
        logger.info(f"🤖 AI response generated: {ai_response[:50]}...")
        
        # Send text response
        await manager.send_message(session_id, {
            "type": "text_response",
            "text": ai_response,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate TTS audio (optional, based on client request)
        if message.get("include_audio", False):
            await manager.send_message(session_id, {
                "type": "processing_status",
                "status": "generating_audio",
                "message": "🔊 Converting to speech...",
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
        logger.error(f"❌ Error processing text input: {e}", exc_info=True)
        await manager.send_message(session_id, {
            "type": "error",
            "message": "Failed to process text input",
            "error_type": type(e).__name__,
            "timestamp": datetime.utcnow().isoformat()
        })


async def handle_audio_input(message: dict, session_id: str, user: dict):
    """Handle audio input from user"""
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    logger.info(f"🎤 Audio input received from {user_id}")
    
    # Send not implemented message for now
    await manager.send_message(session_id, {
        "type": "info",
        "message": "🚧 Audio processing not yet implemented. Please use text input or STT service directly.",
        "timestamp": datetime.utcnow().isoformat()
    })


# STT Webhook (for backward compatibility with STT service)
@app.post("/v1/stt/webhook")
async def stt_webhook(request: dict):
    """Process STT webhook results"""
    try:
        user_id = request.get('user_id', 'webhook_user')
        transcript = request.get('transcript', '')
        session_id = request.get('session_id')
        
        logger.info(f"📝 STT webhook: {transcript[:50]}... from {user_id}")
        
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
        logger.error(f"❌ STT webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)