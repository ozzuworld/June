"""
WebRTC Signaling Manager
Handles SDP offer/answer exchange via WebSocket
"""
import logging
from typing import Dict, Optional, Callable, Awaitable
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class SignalingManager:
    """
    Manages WebRTC signaling over WebSocket
    Handles SDP offers/answers and ICE candidates
    """
    
    def __init__(self):
        self.pending_offers: Dict[str, dict] = {}
        self.on_offer_callback: Optional[Callable] = None
        self.on_ice_candidate_callback: Optional[Callable] = None
        
        logger.info("SignalingManager initialized")
    
    def set_offer_handler(self, callback: Callable[[str, dict], Awaitable[dict]]):
        """
        Set callback for handling WebRTC offers
        
        Args:
            callback: async function(session_id, offer) -> answer
        """
        self.on_offer_callback = callback
        logger.info("Offer handler registered")
    
    def set_ice_candidate_handler(self, callback: Callable[[str, dict], Awaitable[None]]):
        """
        Set callback for handling ICE candidates
        
        Args:
            callback: async function(session_id, candidate)
        """
        self.on_ice_candidate_callback = callback
        logger.info("ICE candidate handler registered")
    
    async def handle_message(self, session_id: str, message: dict) -> Optional[dict]:
        """
        Process incoming signaling message
        
        Args:
            session_id: WebSocket session ID
            message: Signaling message from client
            
        Returns:
            Response message or None
        """
        msg_type = message.get("type")
        
        logger.info(f"[{session_id[:8]}] Received signaling message: {msg_type}")
        
        if msg_type == "webrtc_offer":
            return await self._handle_offer(session_id, message)
        
        elif msg_type == "ice_candidate":
            await self._handle_ice_candidate(session_id, message)
            return None
        
        else:
            logger.warning(f"[{session_id[:8]}] Unknown signaling type: {msg_type}")
            return {
                "type": "error",
                "error": f"Unknown signaling message type: {msg_type}"
            }
    
    async def _handle_offer(self, session_id: str, message: dict) -> dict:
        """Handle WebRTC offer from client"""
        try:
            sdp = message.get("sdp")
            if not sdp:
                raise ValueError("Missing SDP in offer")
            
            # Store offer
            self.pending_offers[session_id] = {
                "sdp": sdp,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            logger.info(f"[{session_id[:8]}] Processing WebRTC offer...")
            
            # Call the offer handler (will be PeerConnectionManager)
            if self.on_offer_callback:
                answer = await self.on_offer_callback(session_id, sdp)
                
                logger.info(f"[{session_id[:8]}] WebRTC answer generated")
                
                return {
                    "type": "webrtc_answer",
                    "sdp": answer,
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                raise RuntimeError("No offer handler registered")
                
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Offer handling error: {e}")
            return {
                "type": "error",
                "error": str(e)
            }
    
    async def _handle_ice_candidate(self, session_id: str, message: dict):
        """Handle ICE candidate from client with enhanced logging"""  
        try:
            candidate = message.get("candidate")
            if not candidate:
                logger.info(f"[{session_id[:8]}] End of ICE candidates from frontend")
                return
            
            # Enhanced logging for frontend candidates
            candidate_str = candidate.get("candidate", "")
            logger.info(f"[{session_id[:8]}] Processing frontend ICE candidate:")
            
            if "typ host" in candidate_str:
                logger.info(f"[{session_id[:8]}]   📱 Frontend host candidate (local IP)")
            elif "typ srflx" in candidate_str:
                logger.info(f"[{session_id[:8]}]   ✅ Frontend srflx candidate (public IP)")
                
            # Your existing callback logic...
            if self.on_ice_candidate_callback:
                await self.on_ice_candidate_callback(session_id, candidate)
                
        except Exception as e:
            logger.error(f"[{session_id[:8]}] ICE candidate error: {e}")

    
    def create_ice_candidate_message(self, candidate: str) -> dict:
        """
        Create ICE candidate message to send to client
        
        Args:
            candidate: ICE candidate string
            
        Returns:
            Message dict ready to send via WebSocket
        """
        return {
            "type": "ice_candidate",
            "candidate": candidate,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def cleanup_session(self, session_id: str):
        """Clean up signaling data for a session"""
        if session_id in self.pending_offers:
            del self.pending_offers[session_id]
            logger.info(f"[{session_id[:8]}] Signaling data cleaned up")


# Global signaling manager instance
signaling_manager = SignalingManager()