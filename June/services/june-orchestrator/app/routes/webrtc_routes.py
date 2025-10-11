"""WebRTC routes for June-Janus integration"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)
webrtc_bp = APIRouter()

@webrtc_bp.get("/health")
async def webrtc_health():
    """WebRTC health check"""
    return {"status": "ok", "service": "webrtc"}

@webrtc_bp.post("/session")
async def create_webrtc_session():
    """Create WebRTC session via Janus"""
    # TODO: Integrate with Janus Gateway
    return {"message": "WebRTC session creation not implemented yet"}

@webrtc_bp.get("/ice-servers")
async def get_ice_servers():
    """Get ICE servers configuration"""
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {
                "urls": "turn:localhost:3478",
                "username": "june-user", 
                "credential": "Pokemon123!"
            }
        ]
    }