import asyncio
import json
import logging
import time
import uuid
import base64
import io
import tempfile
from typing import Dict, Any, Optional, List
import os
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.websockets import WebSocketState

# Import WebRTC components
try:
    # Try relative imports (when running as module)
    from .config import config
    from .webrtc.signaling import signaling_manager
    from .webrtc.peer_connection import peer_connection_manager
    from .webrtc.audio_processor import audio_processor
except ImportError:
    # Fall back to absolute imports (when running directly)
    from app.config import config
    from app.webrtc.signaling import signaling_manager
    from app.webrtc.peer_connection import peer_connection_manager
    from app.webrtc.audio_processor import audio_processor

# Configure logging
logging.basicConfig(level=getattr(logging, config.log_level))
logger = logging.getLogger(__name__)

# Audio session manager for streaming STT
class AudioSession:
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.audio_buffer = io.BytesIO()
        self.buffer_size = 0
        self.last_activity = datetime.utcnow()
        self.is_recording = False
        self.chunk_count = 0
        self.sample_rate = 16000  # Default
        self.format = "wav"
        self.webrtc_enabled = False  # Track if using WebRTC
        
    def add_chunk(self, audio_data: bytes):
        """Add audio chunk to buffer"""
        self.audio_buffer.write(audio_data)
        self.buffer_size += len(audio_data)
        self.chunk_count += 1
        self.last_activity = datetime.utcnow()
        
    def get_buffer_bytes(self) -> bytes:
        """Get all buffered audio as bytes"""
        return self.audio_buffer.getvalue()
        
    def clear_buffer(self):
        """Clear the audio buffer"""
        self.audio_buffer = io.BytesIO()
        self.buffer_size = 0
        self.chunk_count = 0
        
    def should_process(self) -> bool:
        """Check if buffer should be processed (size or time based)"""
        time_threshold = (datetime.utcnow() - self.last_activity).total_seconds() > 2.0
        size_threshold = self.buffer_size > 65536  # 64KB
        return (size_threshold or time_threshold) and self.buffer_size > 0

# Enhanced ConnectionManager with WebRTC support
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
        self.sessions: Dict[str, str] = {}  # session_id -> user_id mapping
        self.audio_sessions: Dict[str, AudioSession] = {}  # session_id -> AudioSession

    async def connect(self, session_id: str, websocket: WebSocket, user: Optional[dict] = None):
        self.connections[session_id] = websocket
        self.users[session_id] = user or {"sub": "anonymous"}
        
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        self.sessions[session_id] = user_id
        
        # Initialize audio session
        self.audio_sessions[session_id] = AudioSession(session_id, user_id)
        
        logger.info(f"🔌 WebSocket connected: {session_id[:8]}... (user: {user_id})")

    async def disconnect(self, session_id: str):
        # Clean up WebRTC connection if exists
        if session_id in peer_connection_manager.peers:
            await peer_connection_manager.close_peer_connection(session_id)
        
        # Clean up audio processing
        if session_id in audio_processor.active_tracks:
            await audio_processor.stop_processing(session_id)
        
        # Clean up WebSocket
        if session_id in self.connections:
            try:
                websocket = self.connections[session_id]
                if websocket.application_state != WebSocketState.DISCONNECTED:
                    await websocket.close()
            except:
                pass
            del self.connections[session_id]
        if session_id in self.users:
            del self.users[session_id]
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.audio_sessions:
            del self.audio_sessions[session_id]
        
        logger.info(f"🔌 WebSocket disconnected: {session_id[:8]}...")

    async def send_message(self, session_id: str, message: dict):
        if session_id not in self.connections:
            logger.warning(f"Session {session_id[:8]}... not found for message")
            return False
        try:
            websocket = self.connections[session_id]
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.send_text(json.dumps(message))
                return True
            else:
                logger.warning(f"WebSocket {session_id[:8]}... not connected")
                return False
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
            websocket = self.connections[session_id]
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.send_bytes(data)
                return True
            else:
                logger.warning(f"WebSocket {session_id[:8]}... not connected")
                return False
        except Exception as e:
            logger.error(f"Failed to send binary data to {session_id[:8]}...: {e}")
            await self.disconnect(session_id)
            return False

    def get_user(self, session_id: str) -> Optional[dict]:
        return self.users.get(session_id)
    
    def get_audio_session(self, session_id: str) -> Optional[AudioSession]:
        return self.audio_sessions.get(session_id)
    
    def find_session_by_user(self, user_id: str) -> Optional[str]:
        """Find active session for a user"""
        for session_id, uid in self.sessions.items():
            if uid == user_id:
                return session_id
        return None

    def get_connection_count(self) -> int:
        return len(self.connections)

# Enhanced auth functions
def generate_session_id() -> str:
    """Generate a unique session ID"""
    return str(uuid.uuid4())

def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode JWT token and return payload"""
    try:
        # This is a simplified version - in production you'd use a proper JWT library
        # For now, we'll extract basic info from the token
        import base64
        
        # Split the JWT token
        parts = token.split('.')
        if len(parts) != 3:
            return None
            
        # Decode the payload (add padding if needed)
        payload = parts[1]
        # Add padding if needed
        payload += '=' * (-len(payload) % 4)
        
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
        
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        return None

async def validate_websocket_token(token: str) -> Optional[dict]:
    """Validate WebSocket token and return user info"""
    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:]
        elif token.startswith('Bearer%20'):
            token = token[9:]  # Handle URL encoding
            
        # Validate the JWT token
        payload = decode_jwt_token(token)
        if not payload:
            # For development, create a mock user
            return {
                'sub': f'user_{token[:8]}',
                'preferred_username': f'user_{token[:8]}',
                'email': 'user@example.com',
                'name': 'Test User'
            }
            
        return {
            'sub': payload.get('sub'),
            'preferred_username': payload.get('preferred_username'),
            'email': payload.get('email'),
            'name': payload.get('name')
        }
        
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        # For development, return a mock user
        return {
            'sub': 'anonymous',
            'preferred_username': 'anonymous',
            'email': 'anonymous@example.com',
            'name': 'Anonymous User'
        }

# STT service integration
async def send_audio_to_stt(audio_bytes: bytes, session_id: str, user_id: str) -> Optional[str]:
    """Send audio to STT service and get transcription"""
    try:
        import httpx
        stt_url = config.services.stt_base_url
        
        # Create a temporary file for the audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
        
        try:
            # Send audio file to STT service
            async with httpx.AsyncClient(timeout=15.0) as client:
                with open(temp_path, "rb") as audio_file:
                    files = {"audio_file": ("audio.wav", audio_file, "audio/wav")}
                    data = {"language": "en"}
                    headers = {
                        "Authorization": f"Bearer {config.services.stt_service_token or 'fallback_token'}",
                        "User-Agent": "june-orchestrator/10.0.0"
                    }
                    
                    response = await client.post(
                        f"{stt_url}/v1/transcribe",
                        files=files,
                        data=data,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        transcript = result.get("text", "").strip()
                        logger.info(f"✅ STT transcription: {transcript[:50]}...")
                        return transcript
                    else:
                        logger.error(f"STT service error: {response.status_code}")
                        return None
                        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"STT service error: {e}")
        return None

# Enhanced AI service
async def generate_ai_response(text: str, user_id: str, session_id: str) -> str:
    """Generate AI response using Gemini"""
    try:
        logger.info(f"🤖 Generating AI response for user {user_id}: {text[:50]}...")
        
        if config.services.gemini_api_key:
            try:
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=config.services.gemini_api_key)
                
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
        
        # Fallback
        text_lower = text.lower()
        if any(greeting in text_lower for greeting in ['hello', 'hi', 'hey']):
            return "Hello! I'm JUNE, your AI assistant from OZZU. How can I help you today?"
        
        return f"I received your message: '{text[:100]}...' I'm here to help! What would you like to know?"
        
    except Exception as e:
        logger.error(f"AI response generation error: {e}")
        return "I apologize, but I'm having trouble generating a response right now."

# TTS service
async def synthesize_speech_binary(text: str, user_id: str = "default") -> Optional[bytes]:
    """Synthesize speech using TTS service"""
    try:
        if not text or len(text.strip()) == 0:
            return None
            
        if len(text) > 1000:
            text = text[:1000] + "..."
            
        logger.info(f"🔊 Binary synthesis: {text[:50]}...")
        
        import httpx
        tts_url = config.services.tts_base_url
        
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

# Binary audio streaming
async def send_binary_audio_chunks(session_id: str, audio_bytes: bytes):
    """Send audio in binary chunks via WebSocket"""
    try:
        chunk_size = 8192
        total_chunks = len(audio_bytes) // chunk_size + (1 if len(audio_bytes) % chunk_size else 0)
        
        logger.info(f"🎵 Streaming {len(audio_bytes)} bytes in {total_chunks} chunks to {session_id[:8]}...")
        
        await manager.send_message(session_id, {
            "type": "audio_stream_start",
            "total_chunks": total_chunks,
            "total_bytes": len(audio_bytes),
            "chunk_size": chunk_size,
            "format": "wav",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        chunks_sent = 0
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            success = await manager.send_binary(session_id, chunk)
            if success:
                chunks_sent += 1
            else:
                break
                
            if chunks_sent % 10 == 0:
                await asyncio.sleep(0.001)
        
        await manager.send_message(session_id, {
            "type": "audio_stream_complete",
            "chunks_sent": chunks_sent,
            "total_chunks": total_chunks,
            "success": chunks_sent == total_chunks,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"✅ Binary audio streaming complete: {chunks_sent}/{total_chunks} chunks")
        
    except Exception as e:
        logger.error(f"Binary audio streaming error: {e}")

# FastAPI app
app = FastAPI(
    title="June Orchestrator", 
    version="10.0.0",
    description="AI Voice Chat Orchestrator with WebRTC & WebSocket Support"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection manager
manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 June Orchestrator v10.0.0 - WebRTC + WebSocket")
    logger.info(f"🔧 WebRTC Enabled: {config.webrtc.enabled}")
    logger.info(f"🔧 TTS URL: {config.services.tts_base_url}")
    logger.info(f"🔧 STT URL: {config.services.stt_base_url}")
    logger.info(f"🔧 Gemini API: {'Configured' if config.services.gemini_api_key else 'Not configured'}")
    
    # Wire up WebRTC components
    if config.webrtc.enabled:
        logger.info("🔌 Wiring WebRTC components...")
        
        # 🚨 CRITICAL: Wire WebSocket manager to PeerConnectionManager
        peer_connection_manager.set_websocket_manager(manager)
        logger.info("✅ WebSocket manager wired to PeerConnectionManager")
        
        # Audio processor callback
        async def on_audio_ready(session_id: str, audio_bytes: bytes):
            """Called when audio buffer is ready from WebRTC"""
            logger.info(f"[{session_id[:8]}] 🎤 Audio ready: {len(audio_bytes)} bytes")
            
            user = manager.get_user(session_id)
            user_id = user.get("sub", "anonymous") if user else "anonymous"
            
            # Send to STT
            transcript = await send_audio_to_stt(audio_bytes, session_id, user_id)
            
            if transcript and transcript.strip():
                # Send transcription
                await manager.send_message(session_id, {
                    "type": "transcription_result",
                    "text": transcript,
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                # Generate AI response
                await process_websocket_message({
                    "type": "text_input",
                    "text": transcript,
                    "source": "webrtc_voice"
                }, session_id, user)
        
        audio_processor.set_audio_ready_handler(on_audio_ready)
        
        # Peer connection callback for audio tracks
        async def on_track_received(session_id: str, track):
            """Called when audio track is received from WebRTC"""
            logger.info(f"[{session_id[:8]}] 🎤 Audio track received, starting processing...")
            await audio_processor.start_processing_track(session_id, track)
        
        peer_connection_manager.set_track_handler(on_track_received)
        
        # Signaling callback for offers
        async def on_webrtc_offer(session_id: str, sdp: str):
            """Called when WebRTC offer is received"""
            logger.info(f"[{session_id[:8]}] 📡 Processing WebRTC offer...")
            answer = await peer_connection_manager.handle_offer(session_id, sdp)
            return answer
        
        signaling_manager.set_offer_handler(on_webrtc_offer)
        
        # ✅ NEW: ICE candidate callback (THIS WAS MISSING!)
        async def on_ice_candidate_from_frontend(session_id: str, candidate: dict):
            """Called when ICE candidate is received from frontend"""
            logger.info(f"[{session_id[:8]}] 🧊 Processing frontend ICE candidate")
            await peer_connection_manager.add_ice_candidate(session_id, candidate)
        
        signaling_manager.set_ice_candidate_handler(on_ice_candidate_from_frontend)
        logger.info("✅ ICE candidate handler wired")
        
        logger.info("✅ WebRTC components wired successfully")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down...")
    await peer_connection_manager.cleanup_all()

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy", 
        "service": "june-orchestrator", 
        "version": "10.0.0",
        "webrtc_enabled": config.webrtc.enabled,
        "connections": manager.get_connection_count(),
        "webrtc_peers": peer_connection_manager.get_connection_count(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/status")
async def get_status():
    return {
        "orchestrator": "healthy",
        "websocket_connections": manager.get_connection_count(),
        "webrtc_connections": peer_connection_manager.get_connection_count(),
        "webrtc_enabled": config.webrtc.enabled,
        "ai_available": bool(config.services.gemini_api_key),
        "tts_available": bool(config.services.tts_base_url),
        "stt_available": bool(config.services.stt_base_url),
        "features": ["websocket", "webrtc", "audio_streaming", "real_time_transcription"],
        "webrtc_stats": peer_connection_manager.get_connection_stats(),
        "audio_stats": audio_processor.get_stats(),
        "timestamp": datetime.utcnow().isoformat(),
        "version": "10.0.0"
    }

# Enhanced WebSocket endpoint with robust error handling
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """Enhanced WebSocket endpoint with better error handling"""
    session_id = None
    user = None
    
    try:
        # Validate token and extract user info
        user = await validate_websocket_token(token)
        if not user:
            logger.warning("❌ Invalid token provided")
            await websocket.close(code=1008, reason="Invalid token")
            return

        await websocket.accept()
        
        # Generate session and register connection
        session_id = generate_session_id()
        await manager.connect(session_id, websocket, user)
        
        logger.info(f"🔌 WebSocket connected: {session_id[:8]}... (user: {user.get('preferred_username', 'unknown')})")
        
        # Send initial connection message
        await manager.send_message(session_id, {
            "type": "connected",
            "session_id": session_id,
            "message": "Connected successfully",
            "timestamp": datetime.utcnow().isoformat(),
            "webrtc_enabled": config.webrtc.enabled,
            "features": ["webrtc", "audio_streaming", "text_chat"] if config.webrtc.enabled else ["text_chat"]
        })
        
        # Message processing loop with enhanced error handling
        while True:
            try:
                # Receive message with proper type handling
                raw_data = await websocket.receive()
                
                # Handle different message types
                if "text" in raw_data:
                    message_text = raw_data["text"]
                    try:
                        message = json.loads(message_text)
                        logger.debug(f"[{session_id[:8]}] Received text message: {message.get('type', 'unknown')}")
                        await process_websocket_message(message, session_id, user)
                    except json.JSONDecodeError as e:
                        logger.error(f"[{session_id[:8]}] JSON decode error: {e}")
                        await manager.send_message(session_id, {
                            "type": "error",
                            "message": "Invalid JSON format"
                        })
                
                elif "bytes" in raw_data:
                    # Handle binary data (e.g., audio frames)
                    binary_data = raw_data["bytes"]
                    logger.debug(f"[{session_id[:8]}] Received binary data: {len(binary_data)} bytes")
                    
                    if config.webrtc.enabled:
                        # Process binary audio data if WebRTC is enabled
                        await process_binary_message(binary_data, session_id)
                    else:
                        logger.warning(f"[{session_id[:8]}] Received binary data but WebRTC is disabled")
                
                else:
                    logger.warning(f"[{session_id[:8]}] Unknown message format: {raw_data}")
                    
            except WebSocketDisconnect:
                logger.info(f"🔌 WebSocket disconnected: {session_id[:8]}...")
                break
                
            except json.JSONDecodeError as e:
                logger.error(f"[{session_id[:8]}] JSON parsing error: {e}")
                await manager.send_message(session_id, {
                    "type": "error",
                    "message": "Invalid message format"
                })
                
            except Exception as e:
                logger.error(f"[{session_id[:8]}] Message loop error: {e}", exc_info=True)
                # Don't break the loop for individual message errors
                await manager.send_message(session_id, {
                    "type": "error",
                    "message": f"Error processing message: {str(e)}"
                })
                
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected: {session_id[:8] if session_id else 'unknown'}...")
        
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}", exc_info=True)
        if websocket.application_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=1011, reason="Internal server error")
            except:
                pass
            
    finally:
        # Clean up connection
        if session_id:
            await manager.disconnect(session_id)
            
            # Clean up WebRTC resources if enabled
            if config.webrtc.enabled:
                try:
                    signaling_manager.cleanup_session(session_id)
                except Exception as e:
                    logger.error(f"Error cleaning up WebRTC session {session_id[:8]}: {e}")

async def process_binary_message(binary_data: bytes, session_id: str):
    """Process binary messages (e.g., audio data)"""
    try:
        # This is where you'd handle binary audio data
        # For now, just log it
        logger.debug(f"[{session_id[:8]}] Processing {len(binary_data)} bytes of binary data")
        
        # TODO: Process audio frames if needed
        # For WebRTC, audio is usually handled through the peer connection
        # not through WebSocket binary messages
        
    except Exception as e:
        logger.error(f"[{session_id[:8]}] Error processing binary data: {e}", exc_info=True)

async def process_websocket_message(message: dict, session_id: str, user: Optional[dict]):
    """Process incoming WebSocket messages with enhanced logging"""
    msg_type = message.get("type", "unknown")
    
    try:
        logger.info(f"[{session_id[:8]}] Processing message: {msg_type}")
        
        # WebRTC signaling messages
        if msg_type in ["webrtc_offer", "ice_candidate"]:
            if config.webrtc.enabled:
                logger.info(f"[{session_id[:8]}] Handling WebRTC signaling: {msg_type}")
                response = await signaling_manager.handle_message(session_id, message)
                if response:
                    logger.info(f"[{session_id[:8]}] Sending WebRTC response: {response.get('type')}")
                    success = await manager.send_message(session_id, response)
                    if success:
                        logger.info(f"[{session_id[:8]}] WebRTC response sent successfully")
                    else:
                        logger.error(f"[{session_id[:8]}] Failed to send WebRTC response")
                else:
                    logger.warning(f"[{session_id[:8]}] No response generated for {msg_type}")
            else:
                logger.warning(f"[{session_id[:8]}] WebRTC not enabled")
                await manager.send_message(session_id, {
                    "type": "error",
                    "message": "WebRTC is not enabled"
                })
        
        elif msg_type == "text_input":
            await handle_text_input(message, session_id, user)
        
        elif msg_type == "ping":
            await manager.send_message(session_id, {
                "type": "pong", 
                "timestamp": datetime.utcnow().isoformat()
            })
        
        else:
            logger.warning(f"[{session_id[:8]}] Unknown message type: {msg_type}")
            await manager.send_message(session_id, {
                "type": "error", 
                "message": f"Unknown message type: {msg_type}"
            })
            
    except Exception as e:
        logger.error(f"[{session_id[:8]}] Error processing {msg_type}: {e}", exc_info=True)
        await manager.send_message(session_id, {
            "type": "error",
            "message": f"Error processing message: {str(e)}"
        })

async def handle_text_input(message: dict, session_id: str, user: Optional[dict]):
    """Handle text input with AI response and TTS"""
    text = message.get("text", "").strip()
    source = message.get("source", "text")
    user_id = user.get("sub", "anonymous") if user else "anonymous"
    
    if not text:
        return
    
    try:
        await manager.send_message(session_id, {
            "type": "processing_status", 
            "status": "thinking", 
            "message": "Generating response..."
        })
        
        ai_response = await generate_ai_response(text, user_id, session_id)
        
        await manager.send_message(session_id, {
            "type": "text_response", 
            "text": ai_response, 
            "user_id": user_id,
            "input_source": source
        })
        
        asyncio.create_task(generate_and_send_audio_optimized(ai_response, session_id, user_id))
        
        await manager.send_message(session_id, {
            "type": "processing_complete"
        })
        
    except Exception as e:
        logger.error(f"Error processing text: {e}")

async def generate_and_send_audio_optimized(text: str, session_id: str, user_id: str):
    """Generate and send audio using binary streaming"""
    try:
        audio_bytes = await synthesize_speech_binary(text, user_id)
        if audio_bytes:
            await send_binary_audio_chunks(session_id, audio_bytes)
    except Exception as e:
        logger.error(f"Audio generation error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=config.host, 
        port=config.port,
        log_level=config.log_level.lower()
    )
