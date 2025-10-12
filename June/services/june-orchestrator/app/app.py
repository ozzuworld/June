"""
June Orchestrator - Janus WebRTC Edition with Full Integration
Coordinates between Janus WebRTC, STT, TTS, and AI services
"""
import logging
import uuid
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict
from datetime import datetime
import aiohttp

from .config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Connection Manager
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
        self.janus_sessions: Dict[str, dict] = {}  # Track Janus sessions
    
    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user or {}
        logger.info(f"✅ Connection registered: {session_id}")
        return session_id
    
    async def disconnect(self, session_id: str):
        # Cleanup Janus session if exists
        if session_id in self.janus_sessions:
            await cleanup_janus_session(session_id, self.janus_sessions[session_id])
            del self.janus_sessions[session_id]
        
        if session_id in self.connections:
            del self.connections[session_id]
        if session_id in self.users:
            del self.users[session_id]
        logger.info(f"🔌 Connection removed: {session_id}")
    
    async def send_message(self, session_id: str, message: dict):
        if session_id not in self.connections:
            logger.warning(f"⚠️ Cannot send message - session not found: {session_id}")
            return
        try:
            websocket = self.connections[session_id]
            await websocket.send_text(json.dumps(message))
            logger.debug(f"📤 Sent {message.get('type', 'unknown')} to {session_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send message to {session_id}: {e}")
            await self.disconnect(session_id)
    
    def get_user(self, session_id: str) -> Optional[dict]:
        return self.users.get(session_id)
    
    def set_janus_session(self, session_id: str, janus_data: dict):
        self.janus_sessions[session_id] = janus_data
    
    def get_janus_session(self, session_id: str) -> Optional[dict]:
        return self.janus_sessions.get(session_id)

manager = ConnectionManager()

# Janus Gateway Integration
JANUS_URL = "http://june-janus.june-services.svc.cluster.local:8088/janus"
JANUS_WS_URL = "ws://june-janus.june-services.svc.cluster.local:8188"

async def create_janus_session(client_session_id: str, user_id: str) -> Optional[dict]:
    """Create Janus session and attach to VideoRoom plugin"""
    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Create Janus session
            transaction_id = str(uuid.uuid4())
            async with session.post(JANUS_URL, json={
                "janus": "create",
                "transaction": transaction_id
            }) as resp:
                data = await resp.json()
                if data.get("janus") != "success":
                    logger.error(f"Failed to create Janus session: {data}")
                    return None
                
                janus_session_id = data["data"]["id"]
                logger.info(f"✅ Janus session created: {janus_session_id}")
            
            # Step 2: Attach to VideoRoom plugin
            transaction_id = str(uuid.uuid4())
            async with session.post(f"{JANUS_URL}/{janus_session_id}", json={
                "janus": "attach",
                "plugin": "janus.plugin.videoroom",
                "transaction": transaction_id
            }) as resp:
                data = await resp.json()
                if data.get("janus") != "success":
                    logger.error(f"Failed to attach to VideoRoom: {data}")
                    return None
                
                handle_id = data["data"]["id"]
                logger.info(f"✅ Attached to VideoRoom plugin: {handle_id}")
            
            # Return session info
            janus_info = {
                "session_id": janus_session_id,
                "handle_id": handle_id,
                "user_id": user_id,
                "client_session_id": client_session_id
            }
            
            return janus_info
            
    except Exception as e:
        logger.error(f"❌ Janus session creation failed: {e}", exc_info=True)
        return None

async def send_janus_message(janus_info: dict, body: dict) -> Optional[dict]:
    """Send message to Janus Gateway"""
    try:
        session_id = janus_info["session_id"]
        handle_id = janus_info["handle_id"]
        transaction_id = str(uuid.uuid4())
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{JANUS_URL}/{session_id}/{handle_id}", json={
                "janus": "message",
                "transaction": transaction_id,
                "body": body
            }) as resp:
                data = await resp.json()
                logger.info(f"📡 Janus response: {data.get('janus', 'unknown')}")
                return data
                
    except Exception as e:
        logger.error(f"❌ Failed to send Janus message: {e}")
        return None

async def handle_webrtc_offer(session_id: str, sdp: str, user_id: str) -> Optional[dict]:
    """Process WebRTC offer through Janus"""
    try:
        # Get or create Janus session
        janus_info = manager.get_janus_session(session_id)
        
        if not janus_info:
            logger.info(f"🎬 Creating new Janus session for {user_id}")
            janus_info = await create_janus_session(session_id, user_id)
            if not janus_info:
                return None
            manager.set_janus_session(session_id, janus_info)
        
        # Join or create a room (using user_id as room identifier)
        room_id = abs(hash(user_id)) % 10000  # Simple room ID from user
        
        logger.info(f"📞 Processing offer for room {room_id}")
        
        # Send join request to Janus
        join_response = await send_janus_message(janus_info, {
            "request": "join",
            "room": room_id,
            "ptype": "publisher",
            "display": user_id
        })
        
        if not join_response:
            # Room doesn't exist, create it
            logger.info(f"🏗️ Creating room {room_id}")
            await send_janus_message(janus_info, {
                "request": "create",
                "room": room_id,
                "publishers": 10,
                "bitrate": 128000,
                "fir_freq": 10,
                "audiocodec": "opus",
                "videocodec": "vp8"
            })
            
            # Now join
            join_response = await send_janus_message(janus_info, {
                "request": "join",
                "room": room_id,
                "ptype": "publisher",
                "display": user_id
            })
        
        # Send the WebRTC offer to Janus
        logger.info(f"📤 Sending offer to Janus")
        
        async with aiohttp.ClientSession() as session:
            transaction_id = str(uuid.uuid4())
            async with session.post(
                f"{JANUS_URL}/{janus_info['session_id']}/{janus_info['handle_id']}",
                json={
                    "janus": "message",
                    "transaction": transaction_id,
                    "body": {
                        "request": "configure",
                        "audio": True,
                        "video": False
                    },
                    "jsep": {
                        "type": "offer",
                        "sdp": sdp
                    }
                }
            ) as resp:
                data = await resp.json()
                
                # Extract answer SDP from Janus response
                if "jsep" in data and "sdp" in data["jsep"]:
                    answer_sdp = data["jsep"]["sdp"]
                    logger.info(f"✅ Got answer from Janus (SDP length: {len(answer_sdp)})")
                    return {
                        "type": "answer",
                        "sdp": answer_sdp
                    }
                else:
                    logger.error(f"No SDP in Janus response: {data}")
                    return None
                    
    except Exception as e:
        logger.error(f"❌ WebRTC offer processing failed: {e}", exc_info=True)
        return None

async def handle_ice_candidate(session_id: str, candidate: dict):
    """Forward ICE candidate to Janus"""
    try:
        janus_info = manager.get_janus_session(session_id)
        if not janus_info:
            logger.warning("⚠️ No Janus session for ICE candidate")
            return
        
        async with aiohttp.ClientSession() as session:
            transaction_id = str(uuid.uuid4())
            async with session.post(
                f"{JANUS_URL}/{janus_info['session_id']}/{janus_info['handle_id']}",
                json={
                    "janus": "trickle",
                    "transaction": transaction_id,
                    "candidate": candidate
                }
            ) as resp:
                data = await resp.json()
                logger.debug(f"🧊 ICE candidate sent to Janus: {data.get('janus')}")
                
    except Exception as e:
        logger.error(f"❌ ICE candidate handling failed: {e}")

async def cleanup_janus_session(session_id: str, janus_info: dict):
    """Cleanup Janus session on disconnect"""
    try:
        async with aiohttp.ClientSession() as session:
            # Leave room
            await session.post(
                f"{JANUS_URL}/{janus_info['session_id']}/{janus_info['handle_id']}",
                json={
                    "janus": "message",
                    "transaction": str(uuid.uuid4()),
                    "body": {"request": "leave"}
                }
            )
            
            # Detach from plugin
            await session.post(
                f"{JANUS_URL}/{janus_info['session_id']}/{janus_info['handle_id']}",
                json={
                    "janus": "detach",
                    "transaction": str(uuid.uuid4())
                }
            )
            
            # Destroy session
            await session.post(
                f"{JANUS_URL}/{janus_info['session_id']}",
                json={
                    "janus": "destroy",
                    "transaction": str(uuid.uuid4())
                }
            )
            
        logger.info(f"🧹 Cleaned up Janus session: {janus_info['session_id']}")
        
    except Exception as e:
        logger.error(f"❌ Janus cleanup failed: {e}")

# Simple token verification
async def verify_token_simple(token: str) -> dict:
    """Simple token verification - decodes JWT without verification"""
    import base64
    import json
    
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        logger.warning(f"⚠️ Using UNVERIFIED token for: {decoded.get('sub', 'unknown')}")
        return decoded
        
    except Exception as e:
        logger.error(f"Token decode failed: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup/shutdown"""
    logger.info("🚀 June Orchestrator v12.0.0 - Janus WebRTC Edition")
    logger.info(f"🔧 Environment: {config.environment}")
    logger.info(f"🔧 Janus Gateway: {JANUS_URL}")
    logger.info(f"🔧 TTS: {config.services.tts_base_url}")
    logger.info(f"🔧 STT: {config.services.stt_base_url}")
    yield
    logger.info("🛑 Shutting down...")

# Create FastAPI app
app = FastAPI(
    title="June Orchestrator",
    version="12.0.0", 
    description="AI Voice Chat Orchestrator with Janus WebRTC",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "12.0.0",
        "status": "running",
        "webrtc": "janus",
        "websocket": "/ws",
        "janus_url": JANUS_URL,
        "features": {
            "janus_webrtc": True,
            "ai": bool(config.services.gemini_api_key),
            "tts": bool(config.services.tts_base_url),
            "stt": bool(config.services.stt_base_url)
        }
    }

@app.get("/healthz")
async def healthz():
    """Kubernetes health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "12.0.0",
        "websocket_connections": len(manager.connections),
        "janus_sessions": len(manager.janus_sessions)
    }

@app.get("/readyz")
async def readyz():
    """Kubernetes readiness check endpoint"""
    return {
        "status": "ready",
        "service": "june-orchestrator"
    }

@app.get("/api/webrtc/config")
async def webrtc_config():
    """WebRTC configuration for frontend"""
    return {
        "janus": {
            "url": JANUS_URL,
            "websocket": JANUS_WS_URL
        },
        "ice_servers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {
                "urls": "turn:turn.ozzu.world:3478",
                "username": "june-user",
                "credential": "Pokemon123!"
            }
        ]
    }

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """
    WebSocket endpoint with Janus WebRTC integration
    """
    
    # Extract token
    auth_token = None
    auth_method = None
    
    if authorization:
        auth_token = authorization.replace('Bearer ', '').replace('Bearer%20', '').strip()
        auth_method = "header"
        logger.info(f"🔑 Token via header (length: {len(auth_token)})")
    elif token:
        auth_token = token.replace('Bearer ', '').replace('Bearer%20', '').strip()
        auth_method = "query"
        logger.info(f"🔑 Token via query (length: {len(auth_token)})")
    
    # Accept connection first
    await websocket.accept()
    logger.info("🔌 WebSocket accepted")
    
    # Authenticate
    user = None
    if auth_token:
        try:
            user = await verify_token_simple(auth_token)
            user_id = user.get("sub", "unknown")
            logger.info(f"✅ Authenticated: {user_id} (via {auth_method})")
        except Exception as e:
            logger.error(f"❌ Auth failed: {e}")
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": "Authentication failed",
                    "error": str(e)
                })
            except:
                pass
            await websocket.close(code=1008, reason="Authentication failed")
            return
    else:
        user = {"sub": "anonymous", "email": "anonymous@example.com"}
    
    # Register connection
    session_id = await manager.connect(websocket, user)
    
    try:
        user_id = user.get("sub", "anonymous")
        
        # Send welcome
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": auth_token is not None,
            "message": f"✅ Connected to June AI with Janus WebRTC",
            "server_time": datetime.utcnow().isoformat()
        })
        
        logger.info(f"🔌 Session established: {session_id} for {user_id}")
        
        # Message loop
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "unknown")
            
            logger.info(f"📨 Message '{msg_type}' from {user_id}")
            
            if msg_type == "ping":
                await manager.send_message(session_id, {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            elif msg_type == "webrtc_offer":
                sdp = message.get("sdp", "")
                logger.info(f"📞 WebRTC offer received (SDP: {len(sdp)} chars)")
                
                # Process through Janus
                answer = await handle_webrtc_offer(session_id, sdp, user_id)
                
                if answer:
                    await manager.send_message(session_id, {
                        "type": "webrtc_answer",
                        "sdp": answer["sdp"],
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    logger.info(f"✅ Sent WebRTC answer to client")
                else:
                    await manager.send_message(session_id, {
                        "type": "error",
                        "message": "Failed to process WebRTC offer"
                    })
            
            elif msg_type == "ice_candidate":
                candidate = message.get("candidate", {})
                logger.info(f"🧊 ICE candidate received")
                await handle_ice_candidate(session_id, candidate)
            
            elif msg_type == "text_input":
                text = message.get("text", "")
                logger.info(f"💬 Text: {text[:50]}...")
                
                # Echo back (add AI processing later)
                await manager.send_message(session_id, {
                    "type": "text_response",
                    "text": f"Received: {text}",
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            else:
                await manager.send_message(session_id, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}"
                })
    
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
        logger.info(f"🔌 Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}", exc_info=True)
        await manager.disconnect(session_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)W