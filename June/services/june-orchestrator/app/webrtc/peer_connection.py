"""
WebRTC Peer Connection Manager
Handles aiortc peer connections for real-time audio streaming
"""
import asyncio
import logging
from typing import Dict, Optional, Callable, Awaitable
from datetime import datetime
import json

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaBlackhole, MediaRecorder

from ..config import config

logger = logging.getLogger(__name__)


class PeerConnectionManager:
    """
    Manages WebRTC peer connections using aiortc
    One peer connection per WebSocket session
    """
    
    def __init__(self):
        self.peers: Dict[str, RTCPeerConnection] = {}
        self.audio_tracks: Dict[str, object] = {}
        self.on_track_callback: Optional[Callable] = None
        self.websocket_manager = None  # Will be set by app.py
        
        # ICE server configuration
        self.ice_servers = self._create_ice_servers()
        self.rtc_configuration = RTCConfiguration(iceServers=self.ice_servers)
        
        logger.info(f"PeerConnectionManager initialized with {len(self.ice_servers)} ICE servers")
    
    def set_websocket_manager(self, manager):
        """Set the WebSocket manager for sending ICE candidates back to frontend"""
        self.websocket_manager = manager
        logger.info("WebSocket manager registered for ICE candidate forwarding")
    
    def _create_ice_servers(self) -> list:
        """Create RTCIceServer list with multiple STUN servers for better connectivity"""
        ice_servers = []
        
        # Add multiple STUN servers for better connectivity across internet
        stun_servers = [
            'stun:stun.l.google.com:19302',
            'stun:stun1.l.google.com:19302',
            'stun:stun2.l.google.com:19302', 
            'stun:stun3.l.google.com:19302',
            'stun:stun.cloudflare.com:3478'
        ]
        
        for stun_url in stun_servers:
            ice_servers.append(RTCIceServer(urls=stun_url))
            logger.info(f"Added STUN server: {stun_url}")
        
        # Add TURN servers if configured
        if config.webrtc.turn_servers:
            for turn_url in config.webrtc.turn_servers:
                turn_server = RTCIceServer(urls=turn_url)
                if config.webrtc.turn_username and config.webrtc.turn_password:
                    turn_server.username = config.webrtc.turn_username
                    turn_server.credential = config.webrtc.turn_password
                ice_servers.append(turn_server)
                logger.info(f"Added TURN server: {turn_url}")
        
        return ice_servers
    
    def set_track_handler(self, callback: Callable[[str, object], Awaitable[None]]):
        """
        Set callback for handling incoming media tracks
        
        Args:
            callback: async function(session_id, track)
        """
        self.on_track_callback = callback
        logger.info("Track handler registered")
    
    async def create_peer_connection(self, session_id: str) -> RTCPeerConnection:
        """
        Create a new RTCPeerConnection for a session
        
        Args:
            session_id: WebSocket session ID
            
        Returns:
            RTCPeerConnection instance
        """
        logger.info(f"[{session_id[:8]}] Creating peer connection...")
        logger.info(f"[{session_id[:8]}] ICE servers configured: {len(self.ice_servers)}")
        
        # Create peer connection with ICE servers
        pc = RTCPeerConnection(configuration=self.rtc_configuration)
        
        # Store the peer connection
        self.peers[session_id] = pc
        
        # Set up event handlers
        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            logger.info(f"[{session_id[:8]}] ICE connection state: {pc.iceConnectionState}")
            
            if pc.iceConnectionState == "connected":
                logger.info(f"[{session_id[:8]}] ✅ ICE connection established successfully!")
            elif pc.iceConnectionState == "checking":
                logger.info(f"[{session_id[:8]}] 🔍 ICE connection checking...")
            elif pc.iceConnectionState == "failed":
                logger.error(f"[{session_id[:8]}] ❌ ICE connection failed")
                logger.error(f"[{session_id[:8]}] This usually means:")
                logger.error(f"[{session_id[:8]}]   1. STUN servers couldn't be reached")
                logger.error(f"[{session_id[:8]}]   2. No server reflexive candidates generated") 
                logger.error(f"[{session_id[:8]}]   3. Firewall blocking WebRTC traffic")
                logger.error(f"[{session_id[:8]}]   4. May need TURN server for NAT traversal")
                await self.close_peer_connection(session_id)
            elif pc.iceConnectionState == "closed":
                logger.info(f"[{session_id[:8]}] ICE connection closed")
        
        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            logger.info(f"[{session_id[:8]}] Connection state: {pc.connectionState}")
            
            if pc.connectionState == "connected":
                logger.info(f"[{session_id[:8]}] ✅ WebRTC connection established!")
            elif pc.connectionState == "failed":
                logger.error(f"[{session_id[:8]}] Connection failed")
                await self.close_peer_connection(session_id)
            elif pc.connectionState == "closed":
                logger.info(f"[{session_id[:8]}] Connection closed")

        # 🚨 CRITICAL FIX: Proper ICE candidate handler
        @pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            if candidate:
                logger.info(f"[{session_id[:8]}] 🧊 Backend ICE candidate generated:")
                logger.info(f"[{session_id[:8]}]   Foundation: {candidate.foundation}")
                logger.info(f"[{session_id[:8]}]   Protocol: {candidate.protocol}")
                logger.info(f"[{session_id[:8]}]   Address: {candidate.ip}")
                logger.info(f"[{session_id[:8]}]   Port: {candidate.port}")
                logger.info(f"[{session_id[:8]}]   Type: {candidate.type}")
                
                if candidate.type == "srflx":
                    logger.info(f"[{session_id[:8]}] ✅ Server reflexive - backend public IP discovered!")
                
                # ✅ CRITICAL FIX: Send ICE candidate to frontend
                if self.websocket_manager:
                    try:
                        # Create candidate dict in format expected by frontend
                        candidate_dict = {
                            "candidate": f"candidate:{candidate.foundation} {candidate.component} {candidate.protocol} {candidate.priority} {candidate.ip} {candidate.port} typ {candidate.type}",
                            "sdpMLineIndex": 0,
                            "sdpMid": "0"
                        }
                        
                        ice_message = {
                            "type": "ice_candidate", 
                            "candidate": candidate_dict
                        }
                        
                        await self.websocket_manager.send_message(session_id, ice_message)
                        logger.info(f"[{session_id[:8]}] ✅ Backend ICE candidate sent to frontend")
                        
                    except Exception as e:
                        logger.error(f"[{session_id[:8]}] ❌ Error sending ICE candidate: {e}")
                else:
                    logger.error(f"[{session_id[:8]}] ❌ No WebSocket manager - cannot send ICE candidate!")
            else:
                logger.info(f"[{session_id[:8]}] 🏁 Backend ICE gathering completed")

        @pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            logger.info(f"[{session_id[:8]}] ICE gathering state: {pc.iceGatheringState}")
            
            if pc.iceGatheringState == "gathering":
                logger.info(f"[{session_id[:8]}] 🔍 Backend starting ICE candidate gathering...")
            elif pc.iceGatheringState == "complete":
                logger.info(f"[{session_id[:8]}] ✅ Backend ICE gathering completed")
        
        @pc.on("track")
        async def on_track(track):
            logger.info(f"[{session_id[:8]}] 🎤 Received {track.kind} track")
            
            if track.kind == "audio":
                # Store the track
                self.audio_tracks[session_id] = track
                
                # Call the track handler (will be AudioProcessor)
                if self.on_track_callback:
                    await self.on_track_callback(session_id, track)
                else:
                    logger.warning(f"[{session_id[:8]}] No track handler registered!")
                
                # Handle track end
                @track.on("ended")
                async def on_ended():
                    logger.info(f"[{session_id[:8]}] Audio track ended")
                    if session_id in self.audio_tracks:
                        del self.audio_tracks[session_id]
        
        logger.info(f"[{session_id[:8]}] Peer connection created successfully")
        return pc
    
    async def handle_offer(self, session_id: str, sdp: str) -> str:
        """
        Handle WebRTC offer from client and create answer
        
        Args:
            session_id: WebSocket session ID
            sdp: SDP offer from client
            
        Returns:
            SDP answer string
        """
        try:
            logger.info(f"[{session_id[:8]}] Processing WebRTC offer...")
            logger.info(f"[{session_id[:8]}] Offer SDP length: {len(sdp)} bytes")
            
            # Create or get peer connection
            if session_id not in self.peers:
                pc = await self.create_peer_connection(session_id)
            else:
                pc = self.peers[session_id]
                logger.warning(f"[{session_id[:8]}] Reusing existing peer connection")
            
            # Parse the offer
            offer = RTCSessionDescription(sdp=sdp, type="offer")
            
            # Set remote description (the offer)
            await pc.setRemoteDescription(offer)
            logger.info(f"[{session_id[:8]}] Remote description set")
            
            # Create answer
            answer = await pc.createAnswer()
            
            # Set local description (our answer)
            await pc.setLocalDescription(answer)
            logger.info(f"[{session_id[:8]}] Local description set")
            
            # Return the SDP answer
            answer_sdp = pc.localDescription.sdp
            logger.info(f"[{session_id[:8]}] ✅ Answer created (SDP length: {len(answer_sdp)} bytes)")
            logger.info(f"[{session_id[:8]}] 🔍 ICE gathering should start now on backend...")
            
            return answer_sdp
            
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Error handling offer: {e}", exc_info=True)
            raise
    
    async def add_ice_candidate(self, session_id: str, candidate: dict):
        """
        Add ICE candidate from client
        
        Args:
            session_id: WebSocket session ID
            candidate: ICE candidate dictionary
        """
        try:
            if session_id not in self.peers:
                logger.warning(f"[{session_id[:8]}] No peer connection for ICE candidate")
                return
            
            pc = self.peers[session_id]
            
            # aiortc handles ICE candidates automatically through signaling
            # This is mainly for logging and monitoring
            logger.debug(f"[{session_id[:8]}] ICE candidate received from frontend")
            logger.debug(f"[{session_id[:8]}] Candidate type: {candidate.get('type', 'unknown')}")
            logger.debug(f"[{session_id[:8]}] Candidate address: {candidate.get('address', 'unknown')}")
            
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Error adding ICE candidate: {e}")
    
    async def close_peer_connection(self, session_id: str):
        """
        Close and cleanup peer connection
        
        Args:
            session_id: WebSocket session ID
        """
        try:
            if session_id in self.peers:
                pc = self.peers[session_id]
                
                logger.info(f"[{session_id[:8]}] Closing peer connection...")
                
                # Close the connection
                await pc.close()
                
                # Remove from tracking
                del self.peers[session_id]
                
                logger.info(f"[{session_id[:8]}] Peer connection closed")
            
            # Clean up audio track
            if session_id in self.audio_tracks:
                del self.audio_tracks[session_id]
                logger.info(f"[{session_id[:8]}] Audio track cleaned up")
                
        except Exception as e:
            logger.error(f"[{session_id[:8]}] Error closing peer connection: {e}")
    
    def get_peer_connection(self, session_id: str) -> Optional[RTCPeerConnection]:
        """Get peer connection for a session"""
        return self.peers.get(session_id)
    
    def get_audio_track(self, session_id: str) -> Optional[object]:
        """Get audio track for a session"""
        return self.audio_tracks.get(session_id)
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.peers)
    
    def get_connection_stats(self) -> dict:
        """Get statistics about connections"""
        stats = {
            "total_connections": len(self.peers),
            "active_audio_tracks": len(self.audio_tracks),
            "connections": {}
        }
        
        for session_id, pc in self.peers.items():
            stats["connections"][session_id[:8]] = {
                "connection_state": pc.connectionState,
                "ice_connection_state": pc.iceConnectionState,
                "ice_gathering_state": pc.iceGatheringState,
                "has_audio_track": session_id in self.audio_tracks
            }
        
        return stats
    
    async def cleanup_all(self):
        """Close all peer connections"""
        logger.info("Closing all peer connections...")
        
        session_ids = list(self.peers.keys())
        for session_id in session_ids:
            await self.close_peer_connection(session_id)
        
        logger.info(f"All {len(session_ids)} peer connections closed")


# Global peer connection manager instance
peer_connection_manager = PeerConnectionManager()
