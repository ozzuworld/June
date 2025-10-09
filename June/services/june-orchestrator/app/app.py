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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user or {"sub": "anonymous"}
        
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        self.sessions[session_id] = user_id
        
        # Initialize audio session
        self.audio_sessions[session_id] = AudioSession(session_id, user_id)
        
        logger.info(f"🔌 WebSocket connected: {session_id[:8]}... (user: {user_id})")
        return session_id

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
                await self.connections[session_id].close()
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
async def verify_websocket_token(token: str) -> Optional[Dict]:
    """Verify WebSocket token from query parameter"""
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        
        # For development, accept a simple token validation
        if token and len(token) > 10:
            return {
                "sub": f"user_{token[:8]}",
                "email": f"user@example.com",
                "authenticated": True
            }
        
        return None
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        return None

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
        
        # Peer connection callback
        async def on_track_received(session_id: str, track):
            """Called when audio track is received from WebRTC"""
            logger.info(f"[{session_id[:8]}] 🎤 Audio track received, starting processing...")
            await audio_processor.start_processing_track(session_id, track)
        
        peer_connection_manager.set_track_handler(on_track_received)
        
        # Signaling callback
        async def on_webrtc_offer(session_id: str, sdp: str):
            """Called when WebRTC offer is received"""
            logger.info(f"[{session_id[:8]}] 📡 Processing WebRTC offer...")
            answer = await peer_connection_manager.handle_offer(session_id, sdp)
            return answer
        
        signaling_manager.set_offer_handler(on_webrtc_offer)
        
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

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """WebSocket endpoint with WebRTC signaling support"""
    user = None
    session_id = None
    
    try:
        if token:
            user = await verify_websocket_token(token)
        
        session_id = await manager.connect(websocket, user)
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": user is not None,
            "features": ["websocket", "webrtc", "audio_input", "audio_output", "binary_streaming"],
            "webrtc_enabled": config.webrtc.enabled,
            "ice_servers": config.get_ice_servers() if config.webrtc.enabled else [],
            "timestamp": datetime.utcnow().isoformat(),
            "version": "10.0.0"
        })
        
        while True:
            try:
                # Try text message
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                    message = json.loads(data)
                    await process_websocket_message(message, session_id, user)
                except asyncio.TimeoutError:
                    # Try binary message
                    try:
                        binary_data = await asyncio.wait_for(websocket.receive_bytes(), timeout=0.1)
                        await process_audio_chunk(binary_data, session_id, user)
                    except asyncio.TimeoutError:
                        continue
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"Message loop error: {e}")
                break
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket {session_id[:8] if session_id else 'unknown'}... disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if session_id:
            await manager.disconnect(session_id)

async def process_audio_chunk(audio_data: bytes, session_id: str, user: Optional[dict]):
    """Process incoming binary audio chunk (WebSocket fallback)"""
    try:
        audio_session = manager.get_audio_session(session_id)
        if audio_session and not audio_session.webrtc_enabled:
            audio_session.add_chunk(audio_data)
    except Exception as e:
        logger.error(f"Error processing audio chunk: {e}")

async def process_websocket_message(message: dict, session_id: str, user: Optional[dict]):
    """Process incoming WebSocket messages"""
    msg_type = message.get("type", "unknown")
    
    try:
        # WebRTC signaling messages
        if msg_type in ["webrtc_offer", "ice_candidate"]:
            if config.webrtc.enabled:
                response = await signaling_manager.handle_message(session_id, message)
                if response:
                    await manager.send_message(session_id, response)
            else:
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
            await manager.send_message(session_id, {
                "type": "error", 
                "message": f"Unknown message type: {msg_type}"
            })
            
    except Exception as e:
        logger.error(f"Error processing {msg_type}: {e}")

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