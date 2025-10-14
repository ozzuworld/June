"""LiveKit webhook handler routes"""
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
    """Handle LiveKit webhook events
    
    Events we handle:
    - room_started: Room was created and first participant joined
    - room_finished: Room was closed (all participants left)
    - participant_joined: New participant joined
    - participant_left: Participant left
    - track_published: Audio/video track published
    - track_unpublished: Audio/video track stopped
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
        
        # Handle different event types
        if webhook.event == "room_started":
            await handle_room_started(webhook)
        elif webhook.event == "room_finished":
            await handle_room_finished(webhook)
        elif webhook.event == "participant_joined":
            await handle_participant_joined(webhook)
        elif webhook.event == "participant_left":
            await handle_participant_left(webhook)
        elif webhook.event == "track_published":
            await handle_track_published(webhook)
        elif webhook.event == "track_unpublished":
            await handle_track_unpublished(webhook)
        else:
            logger.debug(f"Unhandled webhook event: {webhook.event}")
        
        return {"status": "received", "event": webhook.event}
        
    except Exception as e:
        logger.error(f"Error handling LiveKit webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_room_started(webhook: LiveKitWebhook):
    """Handle room started event"""
    if not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    logger.info(f"🎆 Room started: {room_name}")
    
    # Could trigger additional setup here


async def handle_room_finished(webhook: LiveKitWebhook):
    """Handle room finished event"""
    if not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    logger.info(f"🏁 Room finished: {room_name}")
    
    # Find session by room name and mark as finished
    for session_id, session in session_manager.sessions.items():
        if session.room_name == room_name:
            session.status = "finished"
            logger.info(f"Marked session {session_id} as finished")
            break


async def handle_participant_joined(webhook: LiveKitWebhook):
    """Handle participant joined event"""
    if not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    participant_name = webhook.participant.get("name")
    
    logger.info(f"👤 Participant joined {room_name}: {participant_name} ({participant_identity})")
    
    # Could trigger welcome message or setup here


async def handle_participant_left(webhook: LiveKitWebhook):
    """Handle participant left event"""
    if not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    participant_name = webhook.participant.get("name")
    
    logger.info(f"👋 Participant left {room_name}: {participant_name} ({participant_identity})")
    
    # Could trigger cleanup or goodbye message here


async def handle_track_published(webhook: LiveKitWebhook):
    """Handle track published event (audio/video started)"""
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")  # 'audio' or 'video'
    
    logger.info(f"🎤 Track published in {room_name}: {track_kind} from {participant_identity}")
    
    # If audio track, this could trigger STT processing
    if track_kind == "audio":
        logger.info(f"Audio track available for STT processing from {participant_identity}")
        # TODO: Integrate with STT service here


async def handle_track_unpublished(webhook: LiveKitWebhook):
    """Handle track unpublished event (audio/video stopped)"""
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")
    
    logger.info(f"🔇 Track unpublished in {room_name}: {track_kind} from {participant_identity}")
    
    # Could stop STT processing here