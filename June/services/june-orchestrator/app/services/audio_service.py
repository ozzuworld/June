"""
Audio Processing Service
Handles audio from LiveKit and processes it through STT/AI/TTS pipeline
"""
import logging

from . import ai_service, stt_service, tts_service

logger = logging.getLogger(__name__)


async def process_livekit_audio(user_id: str, audio_bytes: bytes):
    """
    Process audio received from LiveKit
    
    Complete pipeline: Audio -> STT -> AI -> TTS -> LiveKit
    """
    try:
        logger.info(f"🎤 Processing LiveKit audio from {user_id}: {len(audio_bytes)} bytes")
        
        # Step 1: Transcribe audio
        transcript = await stt_service.transcribe_audio(
            audio_bytes=audio_bytes,
            session_id=user_id,
            user_id=user_id
        )
        
        if not transcript or not transcript.strip():
            logger.warning("Empty transcription")
            return
        
        logger.info(f"📝 Transcript: {transcript[:100]}...")
        
        # Step 2: Generate AI response
        ai_response = await ai_service.generate_response(
            text=transcript,
            user_id=user_id
        )
        
        logger.info(f"🤖 AI Response: {ai_response[:100]}...")
        
        # Step 3: Generate TTS audio
        response_audio = await tts_service.synthesize_binary(
            text=ai_response,
            user_id=user_id
        )
        
        if response_audio:
            logger.info(f"🔊 Generated TTS: {len(response_audio)} bytes")
            
            # Step 4: Send back to LiveKit room
            # TODO: Implement publishing to LiveKit room
            # await publish_audio_to_room(user_id, response_audio)
        
        logger.info(f"✅ Processed audio for {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Audio processing error for {user_id}: {e}")