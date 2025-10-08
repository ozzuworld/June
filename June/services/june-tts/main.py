import os
import torch
import logging
import base64

# Accept Coqui TTS license automatically
os.environ['COQUI_TOS_AGREED'] = '1'

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import FileResponse, Response
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
    description="Advanced Text-to-Speech with Voice Cloning - WebSocket Ready",
    version="2.1.0"
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
    
    # Initialize XTTS-v2 model
    tts_instance = TTS(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        gpu=torch.cuda.is_available()
    ).to(device)
    
    logger.info("TTS instance initialized successfully")
    tts_ready = True

# Health check endpoints
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
            "device": device,
            "version": "2.1.0"
        }
    else:
        raise HTTPException(status_code=503, detail="TTS service not ready")

@app.get("/speakers")
async def get_available_speakers():
    """Get all available pre-trained speakers"""
    try:
        # XTTS-v2 built-in speakers
        default_speakers = [
            "Claribel Dervla", "Daisy Studious", "Gracie Wise", 
            "Tammie Ema", "Alison Dietlinde", "Ana Florence",
            "Annmarie Nele", "Asya Anara", "Brenda Stern",
            "Gitta Nikolina", "Henriette Usha", "Sofia Hellen",
            "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie",
            "Andrew Chipper", "Badr Odhiambo", "Dionisio Schuyler",
            "Royston Min", "Viktor Eka", "Abrahan Mack",
            "Adde Michal", "Baldur Sanjin", "Craig Gutsy",
            "Damien Black", "Gilberto Mathias", "Ilkin Urbano",
            "Kazuhiko Atallah", "Ludvig Milivoj", "Suad Qasim",
            "Torcull Diarmuid", "Viktor Menelaos", "Zacharie Aimilios"
        ]
        
        return {
            "speakers": default_speakers,
            "total": len(default_speakers),
            "default_speaker": default_speakers[0],
            "categories": {
                "female": default_speakers[:15],
                "male": default_speakers[15:]
            }
        }
    except Exception as e:
        logger.error(f"Error getting speakers: {e}")
        return {
            "speakers": ["Claribel Dervla", "Andrew Chipper"],
            "total": 2,
            "default_speaker": "Claribel Dervla"
        }

@app.post("/synthesize")
async def synthesize_speech(request: TTSRequest):
    """Synthesize speech - Returns JSON with base64 audio for WebSocket (Legacy)"""
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        
        # Use provided speaker or default
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        logger.info(f"🎙️ Synthesizing: {request.text[:50]}... (speaker: {speaker_to_use})")
        
        # Generate audio
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        # Read audio file and convert to base64
        with open(output_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
        
        # Clean up temp file
        os.unlink(output_path)
        
        # Return JSON with base64 audio (for WebSocket/API)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        logger.info(f"✅ TTS synthesis completed: {len(audio_bytes)} bytes")
        
        return {
            "audio_data": audio_b64,
            "content_type": "audio/wav",
            "size_bytes": len(audio_bytes),
            "speaker": speaker_to_use,
            "language": request.language,
            "speed": request.speed,
            "text_length": len(request.text)
        }
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/synthesize-binary")
async def synthesize_speech_binary(request: TTSRequest):
    """Synthesize speech - Returns raw binary audio bytes (Optimized)"""
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        logger.info(f"🎙️ Binary synthesis: {request.text[:50]}... (speaker: {speaker_to_use})")
        
        # Generate audio
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        # Read raw binary audio
        with open(output_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
        
        os.unlink(output_path)
        
        logger.info(f"✅ Binary TTS synthesis: {len(audio_bytes)} bytes")
        
        # Return raw binary response
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Length": str(len(audio_bytes)),
                "X-Audio-Speaker": speaker_to_use,
                "X-Audio-Language": request.language,
                "X-Audio-Speed": str(request.speed),
                "X-Text-Length": str(len(request.text))
            }
        )
    
    except Exception as e:
        logger.error(f"❌ Binary synthesis error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/synthesize-stream")
async def synthesize_speech_stream(request: TTSRequest):
    """Synthesize speech with chunked streaming metadata - For WebSocket streaming"""
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        logger.info(f"🎙️ Streaming synthesis: {request.text[:50]}... (speaker: {speaker_to_use})")
        
        # Generate complete audio (XTTS-v2 limitation - can't stream during generation)
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        # Read and prepare for chunking
        with open(output_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
        
        os.unlink(output_path)
        
        # Calculate chunking metadata
        chunk_size = 8192  # 8KB chunks (industry standard)
        total_chunks = len(audio_bytes) // chunk_size + (1 if len(audio_bytes) % chunk_size else 0)
        
        logger.info(f"✅ TTS streaming ready: {total_chunks} chunks ({len(audio_bytes)} bytes)")
        
        # Return metadata for orchestrator to handle streaming
        return {
            "audio_format": "wav",
            "total_chunks": total_chunks,
            "total_bytes": len(audio_bytes),
            "chunk_size": chunk_size,
            "audio_data": base64.b64encode(audio_bytes).decode('utf-8'),  # Full audio for orchestrator chunking
            "speaker": speaker_to_use,
            "language": request.language,
            "speed": request.speed,
            "text_length": len(request.text)
        }
    
    except Exception as e:
        logger.error(f"❌ Streaming synthesis error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/synthesize-file")
async def synthesize_speech_file(request: TTSRequest):
    """Synthesize speech - Returns audio file for direct download"""
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        tts_instance.tts_to_file(
            text=request.text,
            language=request.language,
            speaker=speaker_to_use,
            file_path=output_path,
            speed=request.speed
        )
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="synthesized_speech.wav"
        )
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {str(e)}")
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
        
        logger.info(f"🎭 Voice cloning: {text[:50]}...")
        
        # Clone voice
        tts_instance.tts_to_file(
            text=text,
            speaker_wav=reference_path,
            language=language,
            file_path=output_path
        )
        
        # Clean up reference file
        os.unlink(reference_path)
        
        # For cloning, return file response (typically larger files)
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename=f"cloned_{speaker_name}.wav"
        )
    
    except Exception as e:
        logger.error(f"❌ Voice cloning error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
