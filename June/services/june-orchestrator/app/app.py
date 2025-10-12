"""
June Orchestrator - Janus WebRTC Edition (Fixed Janus Protocol)
Handles Janus async events properly
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
import asyncio
import base64

from .config import config

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Janus configuration
JANUS_URL = "http://june-janus.june-services.svc.cluster.local:8088/janus"

class JanusManager:
    """Manages Janus sessions with proper async event handling"""
    
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
        self.janus_sessions: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, user: dict) -> str:
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user
        logger.info(f"✅ Connection: {session_id}")
        return session_id
    
    async def disconnect(self, session_id: str):
        if session_id in self.janus_sessions:
            await self._cleanup_janus(session_id)
        self.connections.pop(session_id, None)
        self.users.pop(session_id, None)
        logger.info(f"🔌 Disconnected: {session_id}")
    
    async def send(self, session_id: str, message: dict):
        if session_id in self.connections:
            try:
                await self.connections[session_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Send failed: {e}")
                await self.disconnect(session_id)
    
    async def create_janus_session(self, session_id: str, user_id: str) -> bool:
        """Create Janus session and attach VideoRoom"""
        try:
            async with aiohttp.ClientSession() as session:
                # Create session
                async with session.post(JANUS_URL, json={
                    "janus": "create",
                    "transaction": str(uuid.uuid4())
                }) as resp:
                    data = await resp.json()
                    janus_session_id = data["data"]["id"]
                
                # Attach VideoRoom plugin
                async with session.post(f"{JANUS_URL}/{janus_session_id}", json={
                    "janus": "attach",
                    "plugin": "janus.plugin.videoroom",
                    "transaction": str(uuid.uuid4())
                }) as resp:
                    data = await resp.json()
                    handle_id = data["data"]["id"]
                
                self.janus_sessions[session_id] = {
                    "janus_session_id": janus_session_id,
                    "handle_id": handle_id,
                    "user_id": user_id
                }
                
                logger.info(f"✅ Janus session: {janus_session_id}/{handle_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Janus session failed: {e}")
            return False
    
    async def process_offer(self, session_id: str, sdp: str) -> Optional[str]:
        """Process WebRTC offer through Janus with proper event polling"""
        if session_id not in self.janus_sessions:
            user_id = self.users[session_id].get("sub", "anonymous")
            if not await self.create_janus_session(session_id, user_id):
                return None
        
        janus = self.janus_sessions[session_id]
        room_id = abs(hash(janus["user_id"])) % 10000
        
        try:
            async with aiohttp.ClientSession() as session:
                # Join/create room
                async with session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                    json={
                        "janus": "message",
                        "transaction": str(uuid.uuid4()),
                        "body": {
                            "request": "join",
                            "room": room_id,
                            "ptype": "publisher",
                            "display": janus["user_id"]
                        }
                    }
                ) as resp:
                    join_data = await resp.json()
                    
                    # If room doesn't exist, create it
                    if join_data.get("plugindata", {}).get("data", {}).get("error_code"):
                        logger.info(f"🏗️ Creating room {room_id}")
                        await session.post(
                            f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                            json={
                                "janus": "message",
                                "transaction": str(uuid.uuid4()),
                                "body": {
                                    "request": "create",
                                    "room": room_id,
                                    "publishers": 10,
                                    "audiocodec": "opus",
                                    "videocodec": "vp8"
                                }
                            }
                        )
                        # Retry join
                        await session.post(
                            f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                            json={
                                "janus": "message",
                                "transaction": str(uuid.uuid4()),
                                "body": {
                                    "request": "join",
                                    "room": room_id,
                                    "ptype": "publisher",
                                    "display": janus["user_id"]
                                }
                            }
                        )
                
                # Send offer and get transaction ID
                transaction_id = str(uuid.uuid4())
                async with session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
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
                    ack_data = await resp.json()
                    logger.info(f"📨 Janus ack: {ack_data.get('janus')}")
                
                # ✅ CRITICAL FIX: Poll for the actual event with the answer
                max_attempts = 10
                for attempt in range(max_attempts):
                    await asyncio.sleep(0.1)  # Wait 100ms between polls
                    
                    async with session.get(
                        f"{JANUS_URL}/{janus['janus_session_id']}?maxev=1"
                    ) as resp:
                        event_data = await resp.json()
                        
                        # Check if this is our answer event
                        if event_data.get("janus") == "event":
                            jsep = event_data.get("jsep")
                            if jsep and jsep.get("type") == "answer":
                                answer_sdp = jsep.get("sdp")
                                logger.info(f"✅ Got answer from Janus (attempt {attempt + 1})")
                                return answer_sdp
                        
                        # Also check if it's in plugindata
                        plugindata = event_data.get("plugindata", {})
                        if plugindata:
                            jsep = event_data.get("jsep")
                            if jsep and jsep.get("type") == "answer":
                                answer_sdp = jsep.get("sdp")
                                logger.info(f"✅ Got answer from Janus plugindata (attempt {attempt + 1})")
                                return answer_sdp
                
                logger.error(f"❌ No answer after {max_attempts} attempts")
                return None
                        
        except Exception as e:
            logger.error(f"❌ Offer processing failed: {e}", exc_info=True)
            return None
    
    async def handle_ice(self, session_id: str, candidate: dict):
        """Forward ICE candidate to Janus"""
        if session_id not in self.janus_sessions:
            return
        
        janus = self.janus_sessions[session_id]
        
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                    json={
                        "janus": "trickle",
                        "transaction": str(uuid.uuid4()),
                        "candidate": candidate
                    }
                )
            logger.debug("🧊 ICE forwarded")
        except Exception as e:
            logger.error(f"ICE failed: {e}")
    
    async def _cleanup_janus(self, session_id: str):
        """Cleanup Janus session"""
        janus = self.janus_sessions.pop(session_id, None)
        if not janus:
            return
        
        try:
            async with aiohttp.ClientSession() as session:
                # Leave room
                await session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                    json={"janus": "message", "transaction": str(uuid.uuid4()), "body": {"request": "leave"}},
                    timeout=aiohttp.ClientTimeout(total=2)
                )
                # Detach
                await session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}/{janus['handle_id']}",
                    json={"janus": "detach", "transaction": str(uuid.uuid4())},
                    timeout=aiohttp.ClientTimeout(total=2)
                )
                # Destroy
                await session.post(
                    f"{JANUS_URL}/{janus['janus_session_id']}",
                    json={"janus": "destroy", "transaction": str(uuid.uuid4())},
                    timeout=aiohttp.ClientTimeout(total=2)
                )
            logger.info("🧹 Janus cleaned")
        except:
            pass

manager = JanusManager()

def decode_token(token: str) -> dict:
    """Decode JWT without verification (dev only)"""
    parts = token.split('.')
    payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(payload))
    return decoded

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 June Orchestrator v12.0 - Janus WebRTC (Fixed)")
    logger.info(f"🔧 Janus: {JANUS_URL}")
    yield
    logger.info("🛑 Shutdown")

app = FastAPI(title="June Orchestrator", version="12.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "service": "june-orchestrator",
        "version": "12.0.0",
        "janus": JANUS_URL,
        "websocket": "/ws"
    }

@app.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "connections": len(manager.connections),
        "janus_sessions": len(manager.janus_sessions)
    }

@app.get("/api/webrtc/config")
async def webrtc_config():
    return {
        "janus_url": JANUS_URL,
        "ice_servers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "turn:turn.ozzu.world:3478", "username": "june-user", "credential": "Pokemon123!"}
        ]
    }

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    # Get token
    auth_token = (authorization or token or "").replace('Bearer ', '').replace('Bearer%20', '').strip()
    
    # Accept first
    await websocket.accept()
    
    # Auth
    user = {"sub": "anonymous"}
    if auth_token:
        try:
            user = decode_token(auth_token)
            logger.info(f"✅ Auth: {user.get('sub')}")
        except Exception as e:
            logger.error(f"❌ Auth failed: {e}")
            await websocket.send_json({"type": "error", "message": "Auth failed"})
            await websocket.close(code=1008)
            return
    
    # Connect
    session_id = await manager.connect(websocket, user)
    
    try:
        await manager.send(session_id, {
            "type": "connected",
            "user_id": user.get("sub"),
            "session_id": session_id
        })
        
        # Message loop
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            
            logger.info(f"📨 {msg_type} from {user.get('sub')}")
            
            if msg_type == "ping":
                await manager.send(session_id, {"type": "pong"})
            
            elif msg_type == "webrtc_offer":
                answer_sdp = await manager.process_offer(session_id, msg.get("sdp", ""))
                if answer_sdp:
                    await manager.send(session_id, {"type": "webrtc_answer", "sdp": answer_sdp})
                    logger.info("✅ Sent answer to client")
                else:
                    await manager.send(session_id, {"type": "error", "message": "Failed to get answer from Janus"})
            
            elif msg_type == "ice_candidate":
                await manager.handle_ice(session_id, msg.get("candidate", {}))
            
            else:
                await manager.send(session_id, {"type": "error", "message": f"Unknown type: {msg_type}"})
    
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        await manager.disconnect(session_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)