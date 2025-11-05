"""LiveKit webhook handler - focused on AI integration only"""
import logging
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from typing import Optional

from ..models import LiveKitWebhook
from ..core.dependencies import get_session_service
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify LiveKit webhook signature"""
    try:
        if signature.startswith('sha256='):
            signature = signature[7:]
        expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return False


@router.post("/")
async def handle_livekit_webhook(
    request: Request,
    session_service = Depends(get_session_service),
    livekit_signature: Optional[str] = Header(None, alias="livekit-signature")
):
    """Handle LiveKit webhook events - focus on AI integration triggers"""
    try:
        payload = await request.body()
        if livekit_signature and config.livekit.api_secret:
            if not verify_webhook_signature(payload, livekit_signature, config.livekit.api_secret):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")
        webhook_data = await request.json()
        webhook = LiveKitWebhook(**webhook_data)
        logger.debug(f"LiveKit webhook event: {webhook.event}")
        if webhook.event == "track_published":
            await handle_track_published(webhook, session_service)
        elif webhook.event == "track_unpublished":
            await handle_track_unpublished(webhook, session_service)
        else:
            logger.debug(f"LiveKit auto-handled event: {webhook.event}")
        return {"status": "received", "event": webhook.event}
    except Exception as e:
        logger.error(f"Error handling LiveKit webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_track_published(webhook: LiveKitWebhook, session_service):
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")
    logger.info(f"🎤 Track published in {room_name}: {track_kind} from {participant_identity}")
    if track_kind == "audio":
        logger.info(f"🤖 Audio track ready for STT processing from {participant_identity}")
        # Add event to any matching session for the room
        session = session_service.get_session_by_room(room_name)
        if session:
            session_service.add_message(
                session.id,
                "system",
                f"Audio track started by {participant_identity}",
            )
            logger.info(f"Added audio start event to session {session.id} history")


async def handle_track_unpublished(webhook: LiveKitWebhook, session_service):
    if not webhook.track or not webhook.participant or not webhook.room:
        return
    room_name = webhook.room.get("name")
    participant_identity = webhook.participant.get("identity")
    track_kind = webhook.track.get("type")
    logger.info(f"🔇 Track unpublished in {room_name}: {track_kind} from {participant_identity}")
    if track_kind == "audio":
        session = session_service.get_session_by_room(room_name)
        if session:
            session_service.add_message(
                session.id,
                "system",
                f"Audio track stopped by {participant_identity}",
            )
            logger.info(f"Added audio stop event to session {session.id} history")
