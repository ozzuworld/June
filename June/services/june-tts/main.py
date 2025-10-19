# June/services/june-tts/app.py - Add LiveKit room publishing
"""
Enhanced TTS service with LiveKit room participant capability
"""
import os
import torch
import logging
import base64
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import tempfile
import uuid
from TTS.api import TTS

# Import LiveKit participant
from livekit_participant import get_tts_participant, TTSRoomParticipant

# Accept Coqui TTS license
os.environ['COQUI_TOS_AGREED'] = '1'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June TTS Service - LiveKit Integrated",
    description="TTS with LiveKit room participant capability",
    version="3.0.0"
)

# Global TTS instance
tts_instance = None
device = "cuda" if torch.cuda.is_available() else "cpu"
tts_ready = False


class TTSRequest(BaseModel):
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    speed: float = 1.0


class PublishToRoomRequest(BaseModel):
    """Request to publish TTS audio to LiveKit room"""
    room_name: str
    text: str
    language: str = "en"
    speaker: Optional[str] = "Claribel Dervla"
    speed: float = 1.0


@app.on_event("startup")
async def startup_event():
    global tts_instance, tts_ready
    logger.info(f"🚀 Initializing TTS on device: {device}")
    
    # Initialize XTTS-v2 model
    tts_instance = TTS(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        gpu=torch.cuda.is_available()
    ).to(device)
    
    tts_ready = True
    logger.info("✅ TTS instance initialized")
    
    # Connect to LiveKit room as participant
    try:
        logger.info("🔌 Connecting TTS to LiveKit room...")
        participant = await get_tts_participant()
        logger.info("✅ TTS connected to LiveKit room: ozzu-main")
    except Exception as e:
        logger.error(f"❌ Failed to connect to LiveKit: {e}")
        logger.warning("⚠️ TTS will work for direct calls but not room publishing")


@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-tts",
        "tts_ready": tts_ready,
        "device": device
    }


@app.post("/synthesize-binary")
async def synthesize_speech_binary(request: TTSRequest):
    """
    Traditional TTS endpoint - returns audio bytes
    (Kept for backward compatibility)
    """
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        logger.info(f"🎙️ Synthesizing: {request.text[:50]}...")
        
        # Generate audio
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        # Read audio bytes
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        
        os.unlink(output_path)
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav"
        )
        
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/publish-to-room")
async def publish_to_room(
    request: PublishToRoomRequest,
    background_tasks: BackgroundTasks
):
    """
    NEW: Publish TTS audio directly to LiveKit room
    
    This is called by the orchestrator after processing AI response.
    The audio is published to the room where the client is listening.
    """
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    
    try:
        logger.info(f"🔊 Publishing to room: {request.room_name}")
        logger.info(f"📝 Text: {request.text[:100]}...")
        
        # Generate audio
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        # Read audio bytes
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        
        logger.info(f"✅ Audio generated: {len(audio_bytes)} bytes")
        
        # Get TTS participant instance
        participant = await get_tts_participant()
        
        # Ensure connected to correct room
        if participant.room_name != request.room_name:
            logger.warning(f"⚠️ TTS connected to '{participant.room_name}' but request for '{request.room_name}'")
            # For now, we'll publish anyway (single room setup)
        
        # Publish audio to room (background task for non-blocking)
        background_tasks.add_task(
            participant.speak,
            audio_bytes,
            24000  # Sample rate
        )
        
        # Cleanup temp file
        os.unlink(output_path)
        
        return {
            "status": "success",
            "room_name": request.room_name,
            "text_length": len(request.text),
            "audio_size": len(audio_bytes),
            "message": "Audio publishing to room"
        }
        
    except Exception as e:
        logger.error(f"❌ Publish to room error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/speakers")
async def get_speakers():
    """Get available TTS speakers"""
    speakers = [
        "Claribel Dervla", "Daisy Studious", "Gracie Wise",
        "Andrew Chipper", "Badr Odhiambo"
    ]
    return {
        "speakers": speakers,
        "default": "Claribel Dervla"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)