import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, List
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inline ConnectionManager to fix import issue
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user or {"sub": "anonymous"}
        
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        logger.info(f"🔌 WebSocket connected: {session_id[:8]}... (user: {user_id})")
        return session_id

    async def disconnect(self, session_id: str):
        if session_id in self.connections:
            try:
                await self.connections[session_id].close()
            except:
                pass
            del self.connections[session_id]
        if session_id in self.users:
            del self.users[session_id]
        logger.info(f"🔌 WebSocket disconnected: {session_id[:8]}...")

    async def send_message(self, session_id: str, message: dict):
        if session_id not in self.connections:
            return
        try:
            await self.connections[session_id].send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to {session_id[:8]}...: {e}")
            await self.disconnect(session_id)

    def get_user(self, session_id: str) -> Optional[dict]:
        return self.users.get(session_id)

# Inline auth functions
async def verify_websocket_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    try:
        from shared.auth import get_auth_service, AuthError
        if token.startswith("Bearer "):
            token = token[7:]
        auth_service = get_auth_service()
        user_data = await auth_service.verify_bearer(token)
        return user_data
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        return None

# Inline AI service
async def generate_ai_response(text: str, user_id: str) -> str:
    try:
        if os.getenv("GEMINI_API_KEY"):
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"You are JUNE, a helpful AI assistant. User says: {text}",
                config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=1000)
            )
            if response and response.text:
                return response.text.strip()
    except Exception as e:
        logger.error(f"AI error: {e}")
    
    # Fallback response
    return f"I received your message: '{text[:50]}...' I'm currently in basic mode."

# Inline TTS service
async def synthesize_speech(text: str) -> Optional[str]:
    try:
        import httpx
        tts_url = os.getenv("TTS_BASE_URL", "http://june-tts.june-services.svc.cluster.local:8000")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{tts_url}/synthesize", json={
                "text": text, "speaker": "Claribel Dervla", "speed": 1.0, "language": "en"
            })
            response.raise_for_status()
            result = response.json()
            return result.get("audio_data")
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None

# FastAPI app
app = FastAPI(title="June Orchestrator", version="6.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 June Orchestrator v6.1.0 - Fixed")

@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "june-orchestrator", "version": "6.1.0"}

@app.get("/status")
async def get_status():
    return {
        "orchestrator": "healthy",
        "websocket_connections": len(manager.connections),
        "ai_available": bool(os.getenv("GEMINI_API_KEY")),
        "tts_available": bool(os.getenv("TTS_BASE_URL")),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    user = None
    if token:
        user = await verify_websocket_token(token)
    
    session_id = await manager.connect(websocket, user)
    
    try:
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": user is not None,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await process_websocket_message(message, session_id, user)
            
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(session_id)

async def process_websocket_message(message: dict, session_id: str, user: dict):
    msg_type = message.get("type", "unknown")
    
    try:
        if msg_type == "text_input":
            await handle_text_input(message, session_id, user)
        elif msg_type == "ping":
            await manager.send_message(session_id, {"type": "pong", "timestamp": datetime.utcnow().isoformat()})
        else:
            await manager.send_message(session_id, {
                "type": "error", "message": f"Unknown message type: {msg_type}", "timestamp": datetime.utcnow().isoformat()
            })
    except Exception as e:
        logger.error(f"Error processing {msg_type}: {e}")
        await manager.send_message(session_id, {
            "type": "error", "message": "Failed to process message", "timestamp": datetime.utcnow().isoformat()
        })

async def handle_text_input(message: dict, session_id: str, user: dict):
    text = message.get("text", "").strip()
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    if not text:
        return
    
    try:
        # Send processing status
        await manager.send_message(session_id, {
            "type": "processing_status", "status": "thinking", "message": "Generating response...", "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate AI response
        ai_response = await generate_ai_response(text, user_id)
        
        # Send text response
        await manager.send_message(session_id, {
            "type": "text_response", "text": ai_response, "user_id": user_id, "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate TTS
        await manager.send_message(session_id, {
            "type": "processing_status", "status": "generating_audio", "message": "Converting to speech...", "timestamp": datetime.utcnow().isoformat()
        })
        
        audio_data = await synthesize_speech(ai_response)
        if audio_data:
            await manager.send_message(session_id, {
                "type": "audio_response", "audio_data": audio_data, "text": ai_response, "timestamp": datetime.utcnow().isoformat()
            })
        
        await manager.send_message(session_id, {"type": "processing_complete", "timestamp": datetime.utcnow().isoformat()})
        
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        await manager.send_message(session_id, {
            "type": "error", "message": "Failed to process text", "timestamp": datetime.utcnow().isoformat()
        })

@app.post("/v1/stt/webhook")
async def stt_webhook(request: dict):
    try:
        user_id = request.get('user_id', 'webhook_user')
        transcript = request.get('transcript', '')
        logger.info(f"STT webhook: {transcript[:50]}... from {user_id}")
        
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