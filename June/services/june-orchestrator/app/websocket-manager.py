import json
import logging
import uuid
from typing import Dict, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, user: Optional[dict] = None) -> str:
        """Connect a new WebSocket and return session ID"""
        await websocket.accept()
        session_id = str(uuid.uuid4())
        
        self.connections[session_id] = websocket
        self.users[session_id] = user or {"sub": "anonymous"}
        
        user_id = user.get("sub", "anonymous") if user else "anonymous"
        logger.info(f"WebSocket connected: {session_id[:8]}... (user: {user_id})")
        
        return session_id
    
    async def disconnect(self, session_id: str):
        """Disconnect a WebSocket"""
        if session_id in self.connections:
            try:
                await self.connections[session_id].close()
            except:
                pass
            del self.connections[session_id]
            
        if session_id in self.users:
            del self.users[session_id]
        
        logger.info(f"WebSocket disconnected: {session_id[:8]}...")
    
    async def send_message(self, session_id: str, message: dict):
        """Send message to specific session"""
        if session_id not in self.connections:
            logger.warning(f"Session {session_id[:8]}... not found")
            return
            
        try:
            await self.connections[session_id].send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to {session_id[:8]}...: {e}")
            await self.disconnect(session_id)
    
    def get_user(self, session_id: str) -> Optional[dict]:
        """Get user data for session"""
        return self.users.get(session_id)
    
    async def broadcast(self, message: dict, exclude_session: Optional[str] = None):
        """Broadcast message to all connected clients"""
        disconnected = []
        
        for session_id, websocket in self.connections.items():
            if exclude_session and session_id == exclude_session:
                continue
                
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to broadcast to {session_id[:8]}...: {e}")
                disconnected.append(session_id)
        
        # Clean up disconnected sessions
        for session_id in disconnected:
            await self.disconnect(session_id)
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.connections)
    
    def get_user_sessions(self, user_id: str) -> list:
        """Get all sessions for a specific user"""
        sessions = []
        for session_id, user in self.users.items():
            if user and user.get("sub") == user_id:
                sessions.append(session_id)
        return sessions