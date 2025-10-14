"""LiveKit webhook handler - focused on AI integration only"""
import logging
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional

from ..models import LiveKitWebhook
from ..session_manager import session_manager
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify LiveKit webhook signature"""
    try:
        # Remove 'sha256=' prefix if present
        if signature.startswith('sha256='):
            signature = signature[7:]
        
        # Calculate expected signature
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return False


@router.post("/")
async def handle_livekit_webhook(
    request: Request,
    livekit_signature: Optional[str] = Header(None, alias="livekit-signature")
):
    """Handle LiveKit webhook events - focus on AI integration triggers
    
    LiveKit automatically handles:
    - Room lifecycle (creation, cleanup)
    - Participant management 
    - Connection state tracking
    
    We only need to handle:
    - Audio track events for STT/AI processing
    - Custom business logic triggers
    """
    try:
        # Get raw payload
        payload = await request.body()
        
        # Verify webhook signature if provided
        if livekit_signature and config.livekit.api_secret:
            if not verify_webhook_signature(payload, livekit_signature, config.livekit.api_secret):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse webhook data
        webhook_data = await request.json()
        webhook = LiveKitWebhook(**webhook_data)
        
        logger.debug(f"LiveKit webhook event: {webhook.event}")
        
        # Only handle events that require business logic
        if webhook.event == "track_published":
            await handle_track_published(webhook)
        elif webhook.event == "track_unpublished":
            await handle_track_unpublished(webhook)
        else:
            # LiveKit handles these automatically, just log for monitoring
            logger.debug(f"LiveKit auto-handled event: {webhook.event}")
        
        return {"status": "received", "event": webhook.event}
        
    except Exception as e:
        logger.error(f"Error handling LiveKit webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_track_published(webhook: LiveKitWebhook):
    """Handle track published event - trigger AI processing for audio"""
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")  # 'audio' or 'video'
    
    logger.info(f"🎤 Track published in {room_name}: {track_kind} from {participant_identity}")
    
    # Only process audio tracks for AI pipeline
    if track_kind == "audio":
        logger.info(f"🤖 Audio track ready for STT processing from {participant_identity}")
        
        # Find session for room to add to conversation history
        for session_id, session in session_manager.sessions.items():
            if session.room_name == room_name:
                session_manager.add_to_history(
                    session_id, 
                    "system", 
                    f"Audio track started by {participant_identity}"
                )
                logger.info(f"Added audio start event to session {session_id} history")
                break
        
        # TODO: Integrate with STT service here
        # The actual audio processing should be handled by your STT service
        # when it receives the audio stream from LiveKit


async def handle_track_unpublished(webhook: LiveKitWebhook):
    """Handle track unpublished event - cleanup AI processing"""
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")
    
    logger.info(f"🔇 Track unpublished in {room_name}: {track_kind} from {participant_identity}")
    
    if track_kind == "audio":
        # Find session for room to add to conversation history
        for session_id, session in session_manager.sessions.items():
            if session.room_name == room_name:
                session_manager.add_to_history(
                    session_id, 
                    "system", 
                    f"Audio track stopped by {participant_identity}"
                )
                logger.info(f"Added audio stop event to session {session_id} history")
                break
        
        # TODO: Stop STT processing here if needed