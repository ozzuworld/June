"""
Webhook Endpoints
For STT and other service callbacks
"""
import logging
from fastapi import APIRouter, HTTPException

from ..models import TranscriptWebhook
from ..services import ai_service, audio_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/stt/webhook")
async def stt_webhook(webhook: TranscriptWebhook):
    """
    Process STT webhook results
    Legacy endpoint for backward compatibility
    """
    try:
        logger.info(f"STT webhook from {webhook.user_id}: {webhook.text[:50]}...")
        
        # Process with AI
        ai_response = await ai_service.generate_response(
            text=webhook.text,
            user_id=webhook.user_id
        )
        
        # Generate TTS (if needed)
        # audio_bytes = await tts_service.synthesize_binary(...)
        
        return {
            "status": "processed",
            "transcript_id": webhook.transcript_id,
            "user_id": webhook.user_id,
            "ai_response": ai_response[:100] + "..."
        }
        
    except Exception as e:
        logger.error(f"STT webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))