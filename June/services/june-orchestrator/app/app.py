import asyncio
import json
import logging
import time
import uuid
import base64
from typing import Dict, Any, Optional, List
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced ConnectionManager with session tracking
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
        self.sessions: Dict[str, str] = {}  # session_id -> user_id mapping

    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user or {"sub": "anonymous"}
        
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        self.sessions[session_id] = user_id
        
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
        if session_id in self.sessions:
            del self.sessions[session_id]
        logger.info(f"🔌 WebSocket disconnected: {session_id[:8]}...")

    async def send_message(self, session_id: str, message: dict):
        if session_id not in self.connections:
            logger.warning(f"Session {session_id[:8]}... not found for message")
            return False
        try:
            await self.connections[session_id].send_text(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {session_id[:8]}...: {e}")
            await self.disconnect(session_id)
            return False

    async def send_binary(self, session_id: str, data: bytes):
        """Send binary data via WebSocket"""
        if session_id not in self.connections:
            logger.warning(f"Session {session_id[:8]}... not found for binary message")
            return False
        try:
            await self.connections[session_id].send_bytes(data)
            return True
        except Exception as e:
            logger.error(f"Failed to send binary data to {session_id[:8]}...: {e}")
            await self.disconnect(session_id)
            return False

    def get_user(self, session_id: str) -> Optional[dict]:
        return self.users.get(session_id)
    
    def find_session_by_user(self, user_id: str) -> Optional[str]:
        """Find active session for a user"""
        for session_id, uid in self.sessions.items():
            if uid == user_id:
                return session_id
        return None

    def get_connection_count(self) -> int:
        return len(self.connections)

# Enhanced auth functions
async def verify_websocket_token(token: str) -> Optional[Dict]:
    """Verify WebSocket token from query parameter"""
    if not token:
        return None
    try:
        # Handle "Bearer " prefix
        if token.startswith("Bearer "):
            token = token[7:]
        
        # For development, accept a simple token validation
        # In production, integrate with your Keycloak token validation
        if token and len(token) > 10:  # Basic validation
            return {
                "sub": f"user_{token[:8]}",
                "email": f"user@example.com",
                "authenticated": True
            }
        
        # TODO: Replace with actual Keycloak token validation
        # from shared.auth import get_auth_service, AuthError
        # auth_service = get_auth_service()
        # user_data = await auth_service.verify_bearer(token)
        # return user_data
        
        return None
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        return None

# Enhanced AI service with better error handling
async def generate_ai_response(text: str, user_id: str, session_id: str) -> str:
    """Generate AI response using available AI services"""
    try:
        logger.info(f"🤖 Generating AI response for user {user_id}: {text[:50]}...")
        
        # Try Gemini first
        if os.getenv("GEMINI_API_KEY"):
            try:
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
                
                # Enhanced prompt with personality
                prompt = f"""You are JUNE, a helpful and friendly AI assistant created by OZZU. 
                
User says: "{text}"

Please respond in a conversational, helpful manner. Keep responses concise but informative.
If the user is greeting you, introduce yourself as JUNE from OZZU.
"""
                
                response = client.models.generate_content(
                    model='gemini-2.0-flash-exp',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7, 
                        max_output_tokens=500,
                        candidate_count=1
                    )
                )
                
                if response and response.text:
                    ai_text = response.text.strip()
                    logger.info(f"✅ Gemini response: {ai_text[:100]}...")
                    return ai_text
                    
            except Exception as e:
                logger.error(f"Gemini error: {e}")
        
        # Try OpenAI as fallback
        if os.getenv("OPENAI_API_KEY"):
            try:
                import openai
                openai.api_key = os.getenv("OPENAI_API_KEY")
                
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are JUNE, a helpful AI assistant created by OZZU. Be conversational and concise."},
                        {"role": "user", "content": text}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                
                ai_text = response.choices[0].message.content.strip()
                logger.info(f"✅ OpenAI response: {ai_text[:100]}...")
                return ai_text
                
            except Exception as e:
                logger.error(f"OpenAI error: {e}")
        
        # Intelligent fallback responses based on input
        text_lower = text.lower()
        
        if any(greeting in text_lower for greeting in ['hello', 'hi', 'hey', 'good morning', 'good afternoon']):
            return f"Hello! I'm JUNE, your AI assistant from OZZU. How can I help you today?"
        
        if any(question in text_lower for question in ['how are you', 'how do you do']):
            return "I'm doing great, thank you for asking! I'm here and ready to help you with whatever you need."
        
        if any(word in text_lower for word in ['help', 'assist', 'support']):
            return "I'm here to help! I can assist with questions, provide information, have conversations, and more. What would you like to know?"
        
        if 'what' in text_lower and ('name' in text_lower or 'who' in text_lower):
            return "I'm JUNE, an AI assistant created by OZZU. I'm here to help you with information, conversations, and various tasks."
        
        # Generic fallback
        return f"I received your message: '{text[:100]}...' I'm currently in basic mode but I'm here to help! Could you tell me more about what you need assistance with?"
        
    except Exception as e:
        logger.error(f"AI response generation error: {e}")
        return "I apologize, but I'm having trouble generating a response right now. Please try again in a moment."

# Enhanced TTS service with binary streaming support
async def synthesize_speech_binary(text: str, user_id: str = "default") -> Optional[bytes]:
    """Synthesize speech using TTS service - Returns raw audio bytes"""
    try:
        if not text or len(text.strip()) == 0:
            return None
            
        # Limit text length for TTS
        if len(text) > 1000:
            text = text[:1000] + "..."
            
        logger.info(f"🔊 Binary synthesis: {text[:50]}...")
        
        import httpx
        tts_url = os.getenv("TTS_BASE_URL", "http://june-tts.june-services.svc.cluster.local:8000")
        
        # Use new binary endpoint
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{tts_url}/synthesize-binary", json={
                "text": text,
                "speaker": "Claribel Dervla",
                "speed": 1.0,
                "language": "en"
            })
            
            if response.status_code == 200:
                audio_bytes = response.content
                logger.info(f"✅ Binary TTS synthesis: {len(audio_bytes)} bytes")
                return audio_bytes
                    
    except Exception as e:
        logger.error(f"Binary TTS synthesis error: {e}")
        
    return None

# Legacy TTS function for compatibility
async def synthesize_speech(text: str, user_id: str = "default") -> Optional[str]:
    """Synthesize speech using TTS service - Returns base64 audio (Legacy)"""
    try:
        if not text or len(text.strip()) == 0:
            return None
            
        # Limit text length for TTS
        if len(text) > 1000:
            text = text[:1000] + "..."
            
        logger.info(f"🔊 Synthesizing speech: {text[:50]}...")
        
        import httpx
        tts_url = os.getenv("TTS_BASE_URL", "http://june-tts.june-services.svc.cluster.local:8000")
        
        # Try internal TTS service first
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{tts_url}/synthesize", json={
                "text": text,
                "speaker": "Claribel Dervla",  # Default speaker
                "speed": 1.0,
                "language": "en"
            })
            
            if response.status_code == 200:
                result = response.json()
                audio_data = result.get("audio_data")
                if audio_data:
                    logger.info(f"✅ TTS synthesis successful")
                    return audio_data
                    
        # Try external TTS service as fallback
        external_tts_url = os.getenv("EXTERNAL_TTS_URL")
        if external_tts_url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{external_tts_url}/tts/generate", json={
                    "text": text,
                    "voice": "default",
                    "speed": 1.0
                })
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("audio_data")
                    
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}")
        
    return None

# Binary audio streaming functions
async def send_binary_audio_chunks(session_id: str, audio_bytes: bytes):
    """Send audio in binary chunks via WebSocket - Optimized delivery"""
    try:
        chunk_size = 8192  # 8KB chunks (industry standard)
        total_chunks = len(audio_bytes) // chunk_size + (1 if len(audio_bytes) % chunk_size else 0)
        
        logger.info(f"🎵 Streaming {len(audio_bytes)} bytes in {total_chunks} chunks to {session_id[:8]}...")
        
        # Send stream start notification (text message)
        await manager.send_message(session_id, {
            "type": "audio_stream_start",
            "total_chunks": total_chunks,
            "total_bytes": len(audio_bytes),
            "chunk_size": chunk_size,
            "format": "wav",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Send audio chunks as binary messages
        chunks_sent = 0
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            
            # Send binary WebSocket message
            success = await manager.send_binary(session_id, chunk)
            if success:
                chunks_sent += 1
            else:
                logger.error(f"Failed to send chunk {chunks_sent + 1}/{total_chunks}")
                break
                
            # Small delay to prevent overwhelming (can be removed if not needed)
            if chunks_sent % 10 == 0:  # Every 10 chunks
                await asyncio.sleep(0.001)  # 1ms delay
        
        # Send stream complete notification
        await manager.send_message(session_id, {
            "type": "audio_stream_complete",
            "chunks_sent": chunks_sent,
            "total_chunks": total_chunks,
            "success": chunks_sent == total_chunks,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"✅ Binary audio streaming complete: {chunks_sent}/{total_chunks} chunks to {session_id[:8]}...")
        
    except Exception as e:
        logger.error(f"Binary audio streaming error for {session_id[:8]}...: {e}")

async def send_legacy_audio_chunks(session_id: str, audio_data: str):
    """Send Base64 audio in chunks via WebSocket - Legacy compatibility"""
    try:
        chunk_size = 32768  # 32KB chunks for Base64 data
        total_chunks = len(audio_data) // chunk_size + (1 if len(audio_data) % chunk_size else 0)
        
        logger.info(f"🎵 Legacy streaming {len(audio_data)} chars in {total_chunks} chunks to {session_id[:8]}...")
        
        # Send stream start
        await manager.send_message(session_id, {
            "type": "audio_stream_start",
            "total_chunks": total_chunks,
            "encoding": "base64",
            "format": "wav",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Send chunks
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            chunk_index = i // chunk_size
            is_final = i + chunk_size >= len(audio_data)
            
            await manager.send_message(session_id, {
                "type": "audio_chunk",
                "chunk_data": chunk,
                "chunk_index": chunk_index,
                "is_final": is_final
            })
            
            await asyncio.sleep(0.005)  # 5ms between chunks
        
        # Send complete notification
        await manager.send_message(session_id, {
            "type": "audio_stream_complete",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"✅ Legacy audio streaming complete to {session_id[:8]}...")
        
    except Exception as e:
        logger.error(f"Legacy audio streaming error: {e}")

# FastAPI app with enhanced configuration
app = FastAPI(
    title="June Orchestrator", 
    version="8.0.0",
    description="Enhanced AI Voice Chat Orchestrator with Binary WebSocket Streaming"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection manager
manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 June Orchestrator v8.0.0 - Binary WebSocket Streaming")
    logger.info(f"🔧 TTS URL: {os.getenv('TTS_BASE_URL', 'Not configured')}")
    logger.info(f"🔧 Gemini API: {'Configured' if os.getenv('GEMINI_API_KEY') else 'Not configured'}")

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator", 
        "version": "8.0.0",
        "connections": manager.get_connection_count(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/status")
async def get_status():
    return {
        "orchestrator": "healthy",
        "websocket_connections": manager.get_connection_count(),
        "ai_available": bool(os.getenv("GEMINI_API_KEY")) or bool(os.getenv("OPENAI_API_KEY")),
        "tts_available": bool(os.getenv("TTS_BASE_URL")),
        "features": ["binary_streaming", "chunked_delivery", "legacy_compatibility"],
        "timestamp": datetime.utcnow().isoformat(),
        "version": "8.0.0"
    }

# Enhanced WebSocket endpoint with binary streaming support
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """Enhanced WebSocket endpoint with binary audio streaming"""
    user = None
    session_id = None
    
    try:
        # Verify authentication
        if token:
            user = await verify_websocket_token(token)
            if not user:
                await websocket.close(code=4001, reason="Invalid token")
                return
        
        # Connect and get session ID
        session_id = await manager.connect(websocket, user)
        
        # Send connection confirmation
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": user is not None,
            "features": ["binary_audio", "chunked_streaming"],
            "timestamp": datetime.utcnow().isoformat(),
            "version": "8.0.0"
        })
        
        # Main message loop
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                await process_websocket_message(message, session_id, user)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from {session_id[:8]}...: {e}")
                await manager.send_message(session_id, {
                    "type": "error",
                    "message": "Invalid message format",
                    "timestamp": datetime.utcnow().isoformat()
                })
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket {session_id[:8] if session_id else 'unknown'}... disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if session_id:
            await manager.disconnect(session_id)

async def process_websocket_message(message: dict, session_id: str, user: Optional[dict]):
    """Process incoming WebSocket messages with enhanced handling"""
    msg_type = message.get("type", "unknown")
    
    try:
        logger.info(f"📨 Processing {msg_type} from {session_id[:8]}...")
        
        if msg_type == "text_input":
            await handle_text_input(message, session_id, user)
        elif msg_type == "ping":
            await manager.send_message(session_id, {
                "type": "pong", 
                "timestamp": datetime.utcnow().isoformat()
            })
        elif msg_type == "voice_input":
            await handle_voice_input(message, session_id, user)
        elif msg_type == "audio_preference":
            await handle_audio_preference(message, session_id, user)
        else:
            await manager.send_message(session_id, {
                "type": "error", 
                "message": f"Unknown message type: {msg_type}", 
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error processing {msg_type} from {session_id[:8]}...: {e}")
        await manager.send_message(session_id, {
            "type": "error", 
            "message": "Failed to process message", 
            "timestamp": datetime.utcnow().isoformat()
        })

async def handle_audio_preference(message: dict, session_id: str, user: Optional[dict]):
    """Handle client audio preference settings"""
    prefer_binary = message.get("prefer_binary", True)
    prefer_chunked = message.get("prefer_chunked", True)
    
    # Store preferences (in production, save to user profile)
    if session_id not in manager.users:
        manager.users[session_id] = {}
    
    manager.users[session_id]["audio_preferences"] = {
        "binary": prefer_binary,
        "chunked": prefer_chunked
    }
    
    await manager.send_message(session_id, {
        "type": "audio_preference_set",
        "binary": prefer_binary,
        "chunked": prefer_chunked,
        "timestamp": datetime.utcnow().isoformat()
    })

async def handle_text_input(message: dict, session_id: str, user: Optional[dict]):
    """Handle text input with AI response and optimized TTS streaming"""
    text = message.get("text", "").strip()
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    if not text:
        return
    
    try:
        # Send processing status
        await manager.send_message(session_id, {
            "type": "processing_status", 
            "status": "thinking", 
            "message": "Generating response...", 
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate AI response
        ai_response = await generate_ai_response(text, user_id, session_id)
        
        # Send text response immediately
        await manager.send_message(session_id, {
            "type": "text_response", 
            "text": ai_response, 
            "user_id": user_id, 
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Generate TTS in background (don't block text response)
        asyncio.create_task(generate_and_send_audio_optimized(ai_response, session_id, user_id))
        
        # Send processing complete
        await manager.send_message(session_id, {
            "type": "processing_complete", 
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error processing text from {session_id[:8]}...: {e}")
        await manager.send_message(session_id, {
            "type": "error", 
            "message": "Failed to process text input", 
            "timestamp": datetime.utcnow().isoformat()
        })

async def handle_voice_input(message: dict, session_id: str, user: Optional[dict]):
    """Handle voice input (future implementation)"""
    await manager.send_message(session_id, {
        "type": "error", 
        "message": "Voice input not yet implemented via WebSocket", 
        "timestamp": datetime.utcnow().isoformat()
    })

async def generate_and_send_audio_optimized(text: str, session_id: str, user_id: str):
    """Generate and send audio using optimized binary streaming"""
    try:
        # Update status
        await manager.send_message(session_id, {
            "type": "processing_status", 
            "status": "generating_audio", 
            "message": "Converting to speech...", 
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Check user preferences
        user_prefs = manager.users.get(session_id, {}).get("audio_preferences", {})
        prefer_binary = user_prefs.get("binary", True)
        prefer_chunked = user_prefs.get("chunked", True)
        
        if prefer_binary:
            # Use binary streaming (optimized)
            audio_bytes = await synthesize_speech_binary(text, user_id)
            
            if audio_bytes:
                if prefer_chunked:
                    await send_binary_audio_chunks(session_id, audio_bytes)
                else:
                    # Send as single binary message
                    await manager.send_binary(session_id, audio_bytes)
                    await manager.send_message(session_id, {
                        "type": "audio_ready",
                        "size_bytes": len(audio_bytes),
                        "format": "binary_wav"
                    })
            else:
                logger.warning(f"⚠️ Binary TTS failed for {session_id[:8]}...")
        else:
            # Fallback to legacy Base64 streaming
            audio_data = await synthesize_speech(text, user_id)
            
            if audio_data:
                if prefer_chunked:
                    await send_legacy_audio_chunks(session_id, audio_data)
                else:
                    # Send as single JSON message (original method)
                    await manager.send_message(session_id, {
                        "type": "audio_response", 
                        "audio_data": audio_data,
                        "text": text,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    logger.info(f"✅ Legacy audio response sent to {session_id[:8]}...")
            else:
                logger.warning(f"⚠️ Legacy TTS failed for {session_id[:8]}...")
                
    except Exception as e:
        logger.error(f"Audio generation error for {session_id[:8]}...: {e}")

# Enhanced STT webhook with session correlation
@app.post("/v1/stt/webhook")
async def enhanced_stt_webhook(request: dict):
    """Enhanced STT webhook that can trigger WebSocket responses"""
    try:
        user_id = request.get('user_id', 'webhook_user')
        transcript = request.get('transcript', '')
        session_id = request.get('session_id')  # Optional session correlation
        
        logger.info(f"📝 STT webhook: {transcript[:50]}... from {user_id}")
        
        # If session_id provided, try to send via WebSocket
        if session_id and transcript.strip():
            # Find the session and process as WebSocket message
            if session_id in manager.connections:
                user = manager.get_user(session_id)
                await process_websocket_message({
                    "type": "text_input",
                    "text": transcript
                }, session_id, user)
                
                return {
                    "status": "processed_via_websocket",
                    "session_id": session_id,
                    "transcript_length": len(transcript),
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        # Fallback to user lookup
        if transcript.strip():
            session_id = manager.find_session_by_user(user_id)
            if session_id:
                user = manager.get_user(session_id)
                await process_websocket_message({
                    "type": "text_input",
                    "text": transcript
                }, session_id, user)
                
                return {
                    "status": "processed_via_user_lookup",
                    "user_id": user_id,
                    "session_id": session_id,
                    "transcript_length": len(transcript),
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        # Standard webhook response
        return {
            "status": "received",
            "user_id": user_id,
            "transcript_length": len(transcript),
            "timestamp": datetime.utcnow().isoformat(),
            "note": "No active WebSocket session found"
        }
        
    except Exception as e:
        logger.error(f"STT webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Session management endpoints
@app.get("/v1/session/info/{session_id}")
async def get_session_info(session_id: str):
    """Get information about a WebSocket session"""
    if session_id in manager.connections:
        user = manager.get_user(session_id)
        return {
            "session_id": session_id,
            "connected": True,
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        raise HTTPException(status_code=404, detail="Session not found")

@app.get("/v1/sessions")
async def list_active_sessions():
    """List all active WebSocket sessions (admin endpoint)"""
    sessions = []
    for session_id, user in manager.users.items():
        sessions.append({
            "session_id": session_id,
            "user_id": user.get("sub", "anonymous"),
            "connected": session_id in manager.connections,
            "preferences": user.get("audio_preferences", {})
        })
    
    return {
        "sessions": sessions,
        "total_count": len(sessions),
        "timestamp": datetime.utcnow().isoformat()
    }

# Test endpoints for development
@app.post("/v1/test/message")
async def test_send_message(data: dict):
    """Test endpoint to send message to a specific session"""
    session_id = data.get("session_id")
    message = data.get("message", "Test message")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    success = await manager.send_message(session_id, {
        "type": "text_response",
        "text": message,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return {
        "sent": success,
        "session_id": session_id,
        "message": message
    }

@app.post("/v1/test/binary-audio")
async def test_binary_audio(data: dict):
    """Test endpoint for binary audio streaming"""
    session_id = data.get("session_id")
    text = data.get("text", "Hello! This is a binary audio streaming test.")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    # Generate and send test audio
    asyncio.create_task(generate_and_send_audio_optimized(text, session_id, "test_user"))
    
    return {
        "status": "binary_audio_test_initiated",
        "session_id": session_id,
        "text": text
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8080,
        log_level="info",
        access_log=True
    )
