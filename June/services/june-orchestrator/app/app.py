"""
June Orchestrator - Janus WebRTC Edition
Coordinates between Janus WebRTC, STT, TTS, and AI services
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict
from datetime import datetime
import json

from .config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Simple in-memory connection manager
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        import uuid
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user or {}
        logger.info(f"✅ Connection registered: {session_id}")
        return session_id
    
    async def disconnect(self, session_id: str):
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

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup/shutdown"""
    logger.info("🚀 June Orchestrator v12.0.0 - Janus WebRTC Edition")
    logger.info(f"🔧 Environment: {config.environment}")
    logger.info(f"🔧 Janus Gateway: webrtc.ozzu.world")
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

# Simple auth helper (fallback when auth module not available)
async def verify_token_simple(token: str) -> dict:
    """Simple token verification - replace with proper auth"""
    try:
        # Try to import the real auth module
        from .auth import verify_websocket_token
        return await verify_websocket_token(token)
    except ImportError:
        # Fallback for development
        logger.warning("⚠️ Auth module not available, using fallback")
        import jwt
        try:
            # Just decode without verification for development
            decoded = jwt.decode(token, options={"verify_signature": False})
            return decoded
        except Exception as e:
            logger.error(f"Token decode failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

# Simple routes without external dependencies
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "12.0.0",
        "status": "running",
        "webrtc": "janus",
        "websocket": "/ws",
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
        "websocket_connections": len(manager.connections)
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
            "url": "https://janus.ozzu.world/janus",
            "websocket": "wss://webrtc.ozzu.world/ws"
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

@app.post("/api/voice/process")
async def process_voice():
    """Voice processing endpoint"""
    return {"message": "Voice processing with Janus + STT/TTS"}

# ✅ ADD WEBSOCKET ENDPOINT
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """
    WebSocket endpoint for real-time communication
    
    Supports authentication via:
    - Query parameter: /ws?token=<token>
    - Authorization header: Authorization: Bearer <token>
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
    else:
        logger.warning("⚠️ No token provided")
    
    # ✅ CRITICAL: Accept connection FIRST
    await websocket.accept()
    logger.info("🔌 WebSocket accepted")
    
    # Authenticate after accepting
    user = None
    if auth_token:
        try:
            logger.info(f"🔐 Verifying token: {auth_token[:20]}...")
            user = await verify_token_simple(auth_token)
            user_id = user.get("sub", "unknown")
            logger.info(f"✅ Authenticated: {user_id} (via {auth_method})")
        except Exception as e:
            logger.error(f"❌ Auth failed: {e}", exc_info=True)
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
        # Development: allow anonymous
        logger.warning("⚠️ Anonymous connection allowed (development mode)")
        user = {"sub": "anonymous", "email": "anonymous@example.com"}
    
    # Register connection
    session_id = await manager.connect(websocket, user)
    
    try:
        # Send welcome message
        user_id = user.get("sub", "anonymous")
        await manager.send_message(session_id, {
            "type": "connected",
            "user_id": user_id,
            "session_id": session_id,
            "authenticated": auth_token is not None,
            "auth_method": auth_method,
            "message": f"✅ Connected as {user_id}",
            "server_time": datetime.utcnow().isoformat()
        })
        
        logger.info(f"🔌 Session established: {session_id} for {user_id}")
        
        # Message loop
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "unknown")
            
            logger.info(f"📨 Message '{msg_type}' from {user_id}")
            
            # Handle different message types
            if msg_type == "ping":
                await manager.send_message(session_id, {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            elif msg_type == "text_input":
                text = message.get("text", "")
                logger.info(f"💬 Text: {text[:50]}...")
                
                # Echo back for now (add AI processing later)
                await manager.send_message(session_id, {
                    "type": "text_response",
                    "text": f"Echo: {text}",
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
    uvicorn.run(app, host=config.host, port=config.port)