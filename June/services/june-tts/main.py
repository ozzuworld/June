import os
import torch
import logging

# Accept Coqui TTS license automatically - MUST be "1" not "yes"
os.environ['COQUI_TOS_AGREED'] = '1'

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import tempfile
import uuid
from TTS.api import TTS
import numpy as np
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June TTS Service",
    description="Advanced Text-to-Speech with Voice Cloning",
    version="1.0.0"
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
    emotion: Optional[str] = None

class VoiceCloneRequest(BaseModel):
    text: str
    language: str = "en"
    speaker_name: str
    speed: float = 1.0

@app.on_event("startup")
async def startup_event():
    global tts_instance, tts_ready
    logger.info(f"Initializing TTS on device: {device}")
    logger.info(f"CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        logger.info(f"GPU: {torch.cuda.get_device_name()}")
    
    # Initialize XTTS-v2 model with all features
    tts_instance = TTS(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        gpu=torch.cuda.is_available()
    ).to(device)
    
    logger.info("TTS instance initialized successfully")
    tts_ready = True

# Kubernetes health check endpoints
@app.get("/healthz")
async def kubernetes_health_check():
    """Liveness probe for Kubernetes"""
    return {"status": "healthy", "service": "june-tts"}

@app.get("/readyz")
async def kubernetes_readiness_check():
    """Readiness probe for Kubernetes"""
    if tts_ready and tts_instance is not None:
        return {
            "status": "ready", 
            "service": "june-tts",
            "model_loaded": True,
            "device": device
        }
    else:
        raise HTTPException(status_code=503, detail="TTS service not ready")

# Your existing health endpoint (keeping for compatibility)
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "model_loaded": tts_instance is not None
    }

@app.get("/languages")
async def get_supported_languages():
    """Get all supported languages"""
    languages = {
        "en": "English",
        "es": "Spanish", 
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "pl": "Polish",
        "tr": "Turkish",
        "ru": "Russian",
        "nl": "Dutch",
        "cs": "Czech",
        "ar": "Arabic",
        "zh": "Chinese",
        "ja": "Japanese",
        "hu": "Hungarian",
        "ko": "Korean",
        "hi": "Hindi"
    }
    return {"supported_languages": languages, "total": len(languages)}

@app.get("/speakers")
async def get_available_speakers():
    """Get all available pre-trained speakers"""
    try:
        speakers = tts_instance.speakers if hasattr(tts_instance, 'speakers') else []
        return {"speakers": speakers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/synthesize")
async def synthesize_speech(request: TTSRequest):
    """Synthesize speech from text"""
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        
        # Generate speech
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=request.speaker,
            file_path=output_path,
            speed=request.speed
        )
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="synthesized_speech.wav"
        )
    
    except Exception as e:
        logger.error(f"Synthesis error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clone-voice")
async def clone_voice(
    text: str,
    language: str,
    speaker_name: str,
    reference_audio: UploadFile = File(...)
):
    """Clone a voice from reference audio"""
    try:
        # Save uploaded file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            content = await reference_audio.read()
            tmp_file.write(content)
            reference_path = tmp_file.name
        
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        
        # Clone voice and generate speech
        tts_instance.tts_to_file(
            text=text,
            speaker_wav=reference_path,
            language=language,
            file_path=output_path
        )
        
        # Clean up temp file
        os.unlink(reference_path)
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="cloned_voice.wav"
        )
    
    except Exception as e:
        logger.error(f"Voice cloning error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/voice-conversion")  
async def convert_voice(
    source_audio: UploadFile = File(...),
    target_audio: UploadFile = File(...)
):
    """Convert source voice to target voice characteristics"""
    try:
        # Save uploaded files
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as source_tmp:
            source_content = await source_audio.read()
            source_tmp.write(source_content)
            source_path = source_tmp.name
            
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as target_tmp:
            target_content = await target_audio.read()
            target_tmp.write(target_content)
            target_path = target_tmp.name
        
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        
        # Perform voice conversion using TTS voice conversion
        # Note: This requires additional VC models, simplified for demo
        tts_instance.voice_conversion_to_file(
            source_wav=source_path,
            target_wav=target_path,
            file_path=output_path
        )
        
        # Clean up temp files
        os.unlink(source_path)
        os.unlink(target_path)
        
        return FileResponse(
            output_path,
            media_type="audio/wav", 
            filename="converted_voice.wav"
        )
        
    except Exception as e:
        logger.error(f"Voice conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
