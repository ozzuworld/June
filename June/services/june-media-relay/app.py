# June/services/june-media-relay/app.py
# Media relay service for direct client streaming

import os
import jwt
import json
import asyncio
import logging
import time
from typing import Dict, Optional
from dataclasses import dataclass, asdict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import websockets

logger = logging.getLogger("media-relay")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Configuration
JWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY", "your-secret-key-change-in-production")
JWT_ISSUER = os.getenv("JWT_ISSUER", "https://june-idp.allsafe.world/auth/realms/june")
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "ws://june-stt:8080")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://june-tts-proxy:8080")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://june-orchestrator:8080")

app = FastAPI(title="June Media Relay", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@dataclass
class StreamingSession:
    session_id: str
    user_id: str
    utterance_id: str
    websocket: WebSocket
    stt_connection: Optional[object] = None
    created_at: float = None
    last_activity: float = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        self.last_activity = time.time()

# Active streaming sessions
active_sessions: Dict[str, StreamingSession] = {}

class TokenValidator:
    """Validates JWT tokens for media streaming"""
    
    @staticmethod
    def validate_token(token: str) -> Dict:
        """Validate a media streaming token"""
        try:
            payload = jwt.decode(
                token,
                JWT_SIGNING_KEY,
                algorithms=["HS256"],
                audience="media-relay",
                issuer=JWT_ISSUER
            )
            
            logger.info(f"✅ Valid token for session: {payload.get('sid')}")
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("🚫 Token expired")
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"🚫 Invalid token: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

class EventPublisher:
    """Publishes events to orchestrator"""
    
    @staticmethod
    async def publish_event(event_type: str, session_id: str, data: Dict):
        """Publish streaming event to orchestrator"""
        try:
            event = {
                "type": event_type,
                "session_id": session_id,
                "timestamp": time.time(),
                "data": data
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{ORCHESTRATOR_URL}/v1/media/events",
                    json=event,
                    timeout=5.0
                )
                
            logger.debug(f"📤 Published event: {event_type} for session: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to publish event: {e}")

class STTProxy:
    """Proxies audio to STT service"""
    
    @staticmethod
    async def connect_to_stt(session: StreamingSession, language: str = "en-US"):
        """Connect to STT service for streaming"""
        try:
            # Connect to STT WebSocket endpoint
            stt_url = f"{STT_SERVICE_URL.replace('http://', 'ws://')}/v1/stream-direct"
            
            logger.info(f"🔗 Connecting to STT: {stt_url}")
            
            # TODO: Add service-to-service authentication header
            stt_ws = await websockets.connect(stt_url)
            
            # Send configuration
            config_msg = {
                "type": "config",
                "session_id": session.session_id,
                "language": language,
                "sample_rate": 16000,
                "encoding": "pcm16"
            }
            
            await stt_ws.send(json.dumps(config_msg))
            session.stt_connection = stt_ws
            
            logger.info(f"✅ Connected to STT for session: {session.session_id}")
            return stt_ws
            
        except Exception as e:
            logger.error(f"❌ STT connection failed: {e}")
            raise

    @staticmethod
    async def forward_audio_to_stt(session: StreamingSession, audio_data: bytes):
        """Forward audio data to STT service"""
        try:
            if session.stt_connection:
                await session.stt_connection.send(audio_data)
                session.last_activity = time.time()
                
                # Publish activity event
                await EventPublisher.publish_event(
                    "audio_received",
                    session.session_id,
                    {"audio_size": len(audio_data)}
                )
            else:
                logger.warning(f"⚠️ No STT connection for session: {session.session_id}")
                
        except Exception as e:
            logger.error(f"❌ Failed to forward audio to STT: {e}")

    @staticmethod
    async def handle_stt_responses(session: StreamingSession):
        """Handle responses from STT service"""
        try:
            while session.stt_connection:
                try:
                    response = await session.stt_connection.recv()
                    
                    # Forward STT response to client
                    await session.websocket.send_text(response)
                    
                    # Parse and publish event
                    try:
                        stt_data = json.loads(response)
                        await EventPublisher.publish_event(
                            "stt_result",
                            session.session_id,
                            stt_data
                        )
                    except json.JSONDecodeError:
                        pass
                        
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"🔌 STT connection closed for session: {session.session_id}")
                    break
                except Exception as e:
                    logger.error(f"❌ STT response handling error: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"❌ STT response handler failed: {e}")

class TTSProxy:
    """Proxies TTS requests to external service"""
    
    @staticmethod
    async def synthesize_speech(session: StreamingSession, text: str, voice: str = "default"):
        """Request TTS synthesis and stream back to client"""
        try:
            logger.info(f"🎵 TTS request for session: {session.session_id}, text: '{text[:50]}...'")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{TTS_SERVICE_URL}/v1/tts/stream",
                    json={
                        "text": text,
                        "voice": voice,
                        "session_id": session.session_id,
                        "utterance_id": session.utterance_id
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    # Stream audio back to client
                    await session.websocket.send_bytes(response.content)
                    
                    # Publish TTS completion event
                    await EventPublisher.publish_event(
                        "tts_complete",
                        session.session_id,
                        {
                            "text": text,
                            "voice": voice,
                            "audio_size": len(response.content)
                        }
                    )
                    
                    logger.info(f"✅ TTS completed for session: {session.session_id}")
                else:
                    logger.error(f"❌ TTS failed: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ TTS synthesis failed: {e}")

@app.websocket("/v1/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="Media streaming token")
):
    """Main WebSocket endpoint for media streaming"""
    
    # Validate token
    try:
        token_claims = TokenValidator.validate_token(token)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid token")
        return
    
    # Extract session info from token
    session_id = token_claims["sid"]
    user_id = token_claims["sub"]
    utterance_id = token_claims["utterance_id"]
    scopes = token_claims["scope"].split()
    
    # Check required scopes
    if "asr:stream:write" not in scopes:
        await websocket.close(code=4403, reason="Insufficient permissions")
        return
    
    await websocket.accept()
    
    # Create streaming session
    session = StreamingSession(
        session_id=session_id,
        user_id=user_id,
        utterance_id=utterance_id,
        websocket=websocket
    )
    
    active_sessions[session_id] = session
    
    logger.info(f"🎤 Started streaming session: {session_id} for user: {user_id}")
    
    # Publish session started event
    await EventPublisher.publish_event(
        "session_started",
        session_id,
        {"user_id": user_id, "utterance_id": utterance_id}
    )
    
    try:
        # Connect to STT service
        await STTProxy.connect_to_stt(session)
        
        # Start STT response handler
        stt_task = asyncio.create_task(STTProxy.handle_stt_responses(session))
        
        # Handle incoming messages
        while True:
            try:
                message = await websocket.receive()
                
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        # Audio data - forward to STT
                        audio_data = message["bytes"]
                        await STTProxy.forward_audio_to_stt(session, audio_data)
                        
                    elif "text" in message:
                        # Control message
                        try:
                            control_msg = json.loads(message["text"])
                            await handle_control_message(session, control_msg)
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ Invalid control message from session: {session_id}")
                
            except WebSocketDisconnect:
                logger.info(f"🔌 Client disconnected: {session_id}")
                break
                
    except Exception as e:
        logger.error(f"❌ Streaming session error: {e}")
        
    finally:
        # Cleanup
        if session_id in active_sessions:
            del active_sessions[session_id]
        
        if session.stt_connection:
            await session.stt_connection.close()
        
        # Cancel STT task
        if 'stt_task' in locals():
            stt_task.cancel()
        
        # Publish session ended event
        await EventPublisher.publish_event(
            "session_ended",
            session_id,
            {"duration": time.time() - session.created_at}
        )
        
        logger.info(f"🏁 Ended streaming session: {session_id}")

async def handle_control_message(session: StreamingSession, message: Dict):
    """Handle control messages from client"""
    msg_type = message.get("type")
    
    if msg_type == "tts_request":
        # Handle TTS synthesis request
        text = message.get("text", "")
        voice = message.get("voice", "default")
        
        if text:
            await TTSProxy.synthesize_speech(session, text, voice)
    
    elif msg_type == "stop_recording":
        # Signal end of recording to STT
        if session.stt_connection:
            stop_msg = {"type": "stop"}
            await session.stt_connection.send(json.dumps(stop_msg))
    
    elif msg_type == "ping":
        # Respond to ping
        await session.websocket.send_text(json.dumps({"type": "pong"}))
        session.last_activity = time.time()
    
    else:
        logger.warning(f"⚠️ Unknown control message type: {msg_type}")

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-media-relay",
        "active_sessions": len(active_sessions),
        "timestamp": time.time()
    }

@app.get("/v1/sessions")
async def get_active_sessions():
    """Get active streaming sessions info (for monitoring)"""
    sessions_info = []
    
    for session_id, session in active_sessions.items():
        sessions_info.append({
            "session_id": session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "duration": time.time() - session.created_at
        })
    
    return {
        "active_sessions": sessions_info,
        "total": len(sessions_info)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=False
    )