"""
June Orchestrator - Janus WebSocket Edition (SIMPLIFIED)
Clean implementation using WebSocket for bidirectional Janus communication
"""
import logging
import uuid
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict
import base64
import websockets

from .config import config

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Janus WebSocket URL
JANUS_WS_URL = "ws://june-janus.june-services.svc.cluster.local:8188"

class JanusWebSocketManager:
    """Manages Janus sessions using WebSocket for clean async handling"""
    
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
        self.janus_sessions: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, user: dict) -> str:
        session_id = str(uuid.uuid4())
        self.connections[session_id] = websocket
        self.users[session_id] = user
        logger.info(f"✅ Client connected: {session_id}")
        return session_id
    
    async def disconnect(self, session_id: str):
        if session_id in self.janus_sessions:
            await self._cleanup_janus(session_id)
        self.connections.pop(session_id, None)
        self.users.pop(session_id, None)
        logger.info(f"🔌 Client disconnected: {session_id}")
    
    async def send(self, session_id: str, message: dict):
        if session_id in self.connections:
            try:
                await self.connections[session_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Send failed: {e}")
                await self.disconnect(session_id)
    
    async def create_janus_session(self, session_id: str, user_id: str) -> bool:
        """Create Janus session using WebSocket - much simpler than HTTP"""
        try:
            # Connect to Janus WebSocket
            ws = await websockets.connect(JANUS_WS_URL, subprotocols=["janus-protocol"])
            
            # Create session
            create_msg = {
                "janus": "create",
                "transaction": str(uuid.uuid4())
            }
            await ws.send(json.dumps(create_msg))
            
            response = json.loads(await ws.recv())
            if response.get("janus") != "success":
                logger.error(f"Session creation failed: {response}")
                await ws.close()
                return False
            
            janus_session_id = response["data"]["id"]
            
            # Attach to VideoRoom plugin
            attach_msg = {
                "janus": "attach",
                "plugin": "janus.plugin.videoroom",
                "transaction": str(uuid.uuid4()),
                "session_id": janus_session_id
            }
            await ws.send(json.dumps(attach_msg))
            
            response = json.loads(await ws.recv())
            if response.get("janus") != "success":
                logger.error(f"Plugin attach failed: {response}")
                await ws.close()
                return False
            
            handle_id = response["data"]["id"]
            
            # Store session info
            self.janus_sessions[session_id] = {
                "janus_session_id": janus_session_id,
                "handle_id": handle_id,
                "user_id": user_id,
                "ws": ws,
                "pending_transactions": {}
            }
            
            # Start background task to receive Janus messages
            asyncio.create_task(self._janus_message_handler(session_id))
            
            logger.info(f"✅ Janus session created: {janus_session_id}/{handle_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Janus session creation failed: {e}")
            return False
    
    async def _janus_message_handler(self, session_id: str):
        """Background task to handle incoming Janus WebSocket messages"""
        if session_id not in self.janus_sessions:
            return
        
        janus = self.janus_sessions[session_id]
        ws = janus["ws"]
        
        try:
            while True:
                message = await ws.recv()
                data = json.loads(message)
                
                # Handle different message types
                msg_type = data.get("janus")
                
                if msg_type == "ack":
                    # Just acknowledgment, wait for actual event
                    logger.debug(f"Received ack for transaction: {data.get('transaction')}")
                    continue
                
                elif msg_type == "event":
                    # Plugin event - may contain JSEP answer
                    transaction = data.get("transaction")
                    jsep = data.get("jsep")
                    
                    if jsep and jsep.get("type") == "answer":
                        logger.info(f"✅ Received WebRTC answer via WebSocket")
                        
                        # Store answer for pending transaction
                        if transaction and transaction in janus["pending_transactions"]:
                            future = janus["pending_transactions"][transaction]
                            if not future.done():
                                future.set_result(jsep["sdp"])
                        
                        # Also send directly to client
                        await self.send(session_id, {
                            "type": "webrtc_answer",
                            "sdp": jsep["sdp"]
                        })
                    
                    # Log other event data
                    plugin_data = data.get("plugindata", {}).get("data", {})
                    if plugin_data:
                        logger.info(f"Plugin event: {plugin_data.get('videoroom', 'unknown')}")
                
                elif msg_type == "webrtcup":
                    logger.info("🔗 WebRTC connection established!")
                    await self.send(session_id, {
                        "type": "webrtc_status",
                        "status": "connected"
                    })
                
                elif msg_type == "media":
                    media_type = data.get("type")
                    receiving = data.get("receiving")
                    logger.info(f"📺 Media: {media_type} receiving={receiving}")
                
                elif msg_type == "hangup":
                    reason = data.get("reason", "unknown")
                    logger.warning(f"📞 Hangup: {reason}")
                    await self.send(session_id, {
                        "type": "hangup",
                        "reason": reason
                    })
                
                else:
                    logger.debug(f"Janus message: {msg_type}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Janus WebSocket closed for session {session_id}")
        except Exception as e:
            logger.error(f"Janus message handler error: {e}")
    
    async def process_offer(self, session_id: str, sdp: str) -> Optional[str]:
        """Process WebRTC offer through Janus WebSocket - CLEAN AND SIMPLE"""
        if session_id not in self.janus_sessions:
            user_id = self.users[session_id].get("sub", "anonymous")
            if not await self.create_janus_session(session_id, user_id):
                return None
        
        janus = self.janus_sessions[session_id]
        room_id = abs(hash(janus["user_id"])) % 10000
        
        try:
            ws = janus["ws"]
            
            # 1. Join/create room
            join_msg = {
                "janus": "message",
                "body": {
                    "request": "join",
                    "room": room_id,
                    "ptype": "publisher",
                    "display": janus["user_id"]
                },
                "transaction": str(uuid.uuid4()),
                "session_id": janus["janus_session_id"],
                "handle_id": janus["handle_id"]
            }
            await ws.send(json.dumps(join_msg))
            
            # Wait for join acknowledgment
            await asyncio.sleep(0.1)
            
            # 2. Send offer with configure
            transaction_id = str(uuid.uuid4())
            
            # Create future to wait for answer
            future = asyncio.Future()
            janus["pending_transactions"][transaction_id] = future
            
            configure_msg = {
                "janus": "message",
                "body": {
                    "request": "configure",
                    "audio": True,
                    "video": False
                },
                "jsep": {
                    "type": "offer",
                    "sdp": sdp
                },
                "transaction": transaction_id,
                "session_id": janus["janus_session_id"],
                "handle_id": janus["handle_id"]
            }
            
            logger.info(f"📤 Sending WebRTC offer via WebSocket")
            await ws.send(json.dumps(configure_msg))
            
            # 3. Wait for answer (with timeout)
            try:
                answer_sdp = await asyncio.wait_for(future, timeout=10.0)
                logger.info(f"✅ Got answer ({len(answer_sdp)} chars)")
                return answer_sdp
            except asyncio.TimeoutError:
                logger.error("❌ Timeout waiting for answer")
                return None
            finally:
                # Cleanup
                janus["pending_transactions"].pop(transaction_id, None)
            
        except Exception as e:
            logger.error(f"❌ Offer processing failed: {e}")
            return None
    
    async def handle_ice(self, session_id: str, candidate: dict):
        """Forward ICE candidate to Janus via WebSocket"""
        if session_id not in self.janus_sessions:
            return
        
        janus = self.janus_sessions[session_id]
        
        try:
            trickle_msg = {
                "janus": "trickle",
                "candidate": candidate,
                "transaction": str(uuid.uuid4()),
                "session_id": janus["janus_session_id"],
                "handle_id": janus["handle_id"]
            }
            await janus["ws"].send(json.dumps(trickle_msg))
            logger.debug("🧊 ICE candidate forwarded")
        except Exception as e:
            logger.error(f"ICE forwarding failed: {e}")
    
    async def _cleanup_janus(self, session_id: str):
        """Cleanup Janus session"""
        janus = self.janus_sessions.pop(session_id, None)
        if not janus:
            return
        
        try:
            ws = janus["ws"]
            
            # Send hangup
            hangup_msg = {
                "janus": "hangup",
                "transaction": str(uuid.uuid4()),
                "session_id": janus["janus_session_id"],
                "handle_id": janus["handle_id"]
            }
            await ws.send(json.dumps(hangup_msg))
            
            # Wait a moment
            await asyncio.sleep(0.1)
            
            # Close WebSocket
            await ws.close()
            
            logger.info("🧹 Janus session cleaned up")
        except Exception as e:
            logger.debug(f"Cleanup error (non-fatal): {e}")


manager = JanusWebSocketManager()


def decode_token(token: str) -> dict:
    """Decode JWT without verification (dev only)"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {"sub": "anonymous"}
        payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return decoded
    except Exception:
        return {"sub": "anonymous"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 June Orchestrator v13.0 - Janus WebSocket (Simplified)")
    logger.info(f"🔧 Janus WebSocket: {JANUS_WS_URL}")
    yield
    logger.info("🛑 Shutdown")


app = FastAPI(title="June Orchestrator", version="13.0.0", lifespan=lifespan)

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
        "version": "13.0.0",
        "janus": JANUS_WS_URL,
        "websocket": "/ws",
        "transport": "WebSocket (simplified)"
    }


@app.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "connections": len(manager.connections),
        "janus_sessions": len(manager.janus_sessions),
        "transport": "websocket"
    }


@app.get("/api/webrtc/config")
async def webrtc_config():
    return {
        "janus_ws_url": JANUS_WS_URL,
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
    """Main WebSocket endpoint - handles both client and Janus communication"""
    
    # Get token
    auth_token = (authorization or token or "").replace('Bearer ', '').replace('Bearer%20', '').strip()
    
    # Accept connection
    await websocket.accept()
    
    # Authenticate
    user = {"sub": "anonymous"}
    if auth_token:
        try:
            user = decode_token(auth_token)
            logger.info(f"✅ Authenticated: {user.get('sub')}")
        except Exception as e:
            logger.error(f"❌ Auth failed: {e}")
            await websocket.send_json({"type": "error", "message": "Authentication failed"})
            await websocket.close(code=1008)
            return
    
    # Connect
    session_id = await manager.connect(websocket, user)
    
    try:
        # Send connection confirmation
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
                    await manager.send(session_id, {
                        "type": "webrtc_answer",
                        "sdp": answer_sdp
                    })
                else:
                    await manager.send(session_id, {
                        "type": "error",
                        "message": "Failed to process offer"
                    })
            
            elif msg_type == "ice_candidate":
                await manager.handle_ice(session_id, msg.get("candidate", {}))
            
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                await manager.send(session_id, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}"
                })
    
    except WebSocketDisconnect:
        await manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}", exc_info=True)
        await manager.disconnect(session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)