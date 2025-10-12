"""
WebSocket Connection Manager
Manages active WebSocket connections and message broadcasting
"""
import logging
from typing import Dict, Optional
from fastapi import WebSocket
import json

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        """Register a new WebSocket connection"""
        import uuid
        session_id = str(uuid.uuid4())
        
        self.connections[session_id] = websocket
        self.users[session_id] = user or {}
        
        logger.info(f"✅ Connection registered: {session_id}")
        return session_id
    
    async def disconnect(self, session_id: str):
        """Remove a WebSocket connection"""
        if session_id in self.connections:
            del self.connections[session_id]
        if session_id in self.users:
            del self.users[session_id]
        
        logger.info(f"🔌 Connection removed: {session_id}")
    
    async def send_message(self, session_id: str, message: dict):
        """Send a message to a specific connection"""
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
    
    async def broadcast(self, message: dict, exclude: Optional[str] = None):
        """Broadcast a message to all connections"""
        disconnected = []
        
        for session_id, websocket in self.connections.items():
            if session_id == exclude:
                continue
            
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"❌ Failed to broadcast to {session_id}: {e}")
                disconnected.append(session_id)
        
        # Clean up disconnected sessions
        for session_id in disconnected:
            await self.disconnect(session_id)
    
    def get_user(self, session_id: str) -> Optional[dict]:
        """Get user data for a session"""
        return self.users.get(session_id)
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.connections)