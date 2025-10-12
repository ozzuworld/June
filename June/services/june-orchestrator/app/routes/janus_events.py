"""Janus event handler routes"""
import logging
from fastapi import APIRouter, Request
from typing import Dict, Any

from ..session_manager import session_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/")
async def handle_janus_event(request: Request):
    """
    Handle events from Janus event handler plugin
    
    Events we care about:
    - type 1: Session created
    - type 2: Session destroyed  
    - type 8: Plugin attached
    - type 64: WebRTC state (webrtcup/hangup)
    - type 256: Media state (receiving audio/video)
    """
    try:
        event = await request.json()
        event_type = event.get("type")
        
        logger.debug(f"Janus event type={event_type}: {event}")
        
        # Handle specific events
        if event_type == 64:  # WebRTC state
            await handle_webrtc_state(event)
        elif event_type == 256:  # Media state
            await handle_media_state(event)
        elif event_type == 2:  # Session destroyed
            await handle_session_destroyed(event)
        
        return {"status": "received", "type": event_type}
        
    except Exception as e:
        logger.error(f"Error handling Janus event: {e}")
        return {"status": "error", "message": str(e)}


async def handle_webrtc_state(event: Dict[str, Any]):
    """Handle WebRTC up/down events"""
    event_data = event.get("event", {})
    
    if "webrtcup" in event_data:
        logger.info("🔗 WebRTC connection established")
        # Could trigger something here
        
    elif "hangup" in event_data:
        logger.info("📞 WebRTC hangup")
        # Could cleanup something here


async def handle_media_state(event: Dict[str, Any]):
    """Handle media receiving events"""
    event_data = event.get("event", {})
    
    if event_data.get("receiving") and event_data.get("type") == "audio":
        logger.info("🎵 Audio is being received")
        # This is where you might trigger STT processing


async def handle_session_destroyed(event: Dict[str, Any]):
    """Handle session destruction"""
    janus_session_id = event.get("session_id")
    logger.info(f"🗑️ Janus session destroyed: {janus_session_id}")
    # Could cleanup business session here