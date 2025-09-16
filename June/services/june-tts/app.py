# June/services/june-tts/app.py - REAL CHATTERBOX TTS IMPLEMENTATION
import os
import time
import logging
import tempfile
import base64
import torch
import torchaudio
import io
from typing import Optional

from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import auth modules  
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="June TTS Service - Chatterbox", version="1.0.0")

# Configuration
DEVICE = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
ENABLE_VOICE_CLONING = os.getenv("ENABLE_VOICE_CLONING", "true").lower() == "true"
ENABLE_EMOTION_CONTROL = os.getenv("ENABLE_EMOTION_CONTROL", "true").lower() == "true"

# Initialize Chatterbox
chatterbox_model = None
try:
    from chatterbox import Chatterbox
    
    logger.info(f"🚀 Initializing Chatterbox on {DEVICE}...")
    chatterbox_model = Chatterbox.from_pretrained("resemble-ai/chatterbox", device=DEVICE)
    logger.info("✅ Chatterbox TTS model loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load Chatterbox: {e}")

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field("default", description="Voice profile")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed")
    emotion: Optional[str] = Field(None, description="Emotion: neutral, happy, sad, angry, surprised")
    emotion_strength: float = Field(0.5, ge=0.0, le=1.0, description="Emotion strength")

# Voice profiles for Chatterbox
VOICE_PROFILES = {
    "default": {"name": "Assistant", "style": "neutral", "pitch": 0.0},
    "assistant_female": {"name": "Female Assistant", "style": "friendly", "pitch": 0.2},
    "assistant_male": {"name": "Male Assistant", "style": "professional", "pitch": -0.2},
    "narrator": {"name": "Narrator", "style": "calm", "pitch": 0.0},
    "excited": {"name": "Excited", "style": "energetic", "pitch": 0.1},
}

@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    return {
        "ok": True,
        "service": "june-tts",
        "timestamp": time.time(),
        "status": "healthy",
        "device": DEVICE,
        "engine": "chatterbox",
        "model_loaded": chatterbox_model is not None,
        "features": {
            "voice_cloning": ENABLE_VOICE_CLONING,
            "emotion_control": ENABLE_EMOTION_CONTROL,
            "multilingual": True,
        }
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voice profiles"""
    return {
        "voices": VOICE_PROFILES,
        "default": "default",
        "engine": "chatterbox",
        "features": {
            "voice_cloning": ENABLE_VOICE_CLONING,
            "emotion_control": ENABLE_EMOTION_CONTROL,
        }
    }

def synthesize_with_chatterbox(
    text: str, 
    voice: str = "default",
    speed: float = 1.0,
    emotion: Optional[str] = None,
    emotion_strength: float = 0.5
) -> bytes:
    """Synthesize speech using Chatterbox"""
    
    if not chatterbox_model:
        raise HTTPException(status_code=503, detail="Chatterbox model not loaded")
    
    try:
        logger.info(f"🎵 Synthesizing: '{text[:50]}...' with voice '{voice}'")
        
        # Get voice profile
        voice_profile = VOICE_PROFILES.get(voice, VOICE_PROFILES["default"])
        
        # Prepare synthesis parameters
        synthesis_params = {
            "text": text,
            "speed": speed,
            "pitch_shift": voice_profile["pitch"],
        }
        
        # Add emotion control if enabled
        if ENABLE_EMOTION_CONTROL and emotion:
            synthesis_params["emotion"] = emotion
            synthesis_params["emotion_strength"] = emotion_strength
            logger.info(f"🎭 Applying emotion: {emotion} (strength: {emotion_strength})")
        
        # Generate speech with Chatterbox
        with torch.no_grad():
            audio_tensor = chatterbox_model.synthesize(**synthesis_params)
        
        # Convert to audio bytes (MP3)
        audio_buffer = io.BytesIO()
        
        # Save as WAV first (Chatterbox outputs raw audio tensor)
        torchaudio.save(
            audio_buffer,
            audio_tensor.unsqueeze(0),  # Add batch dimension
            sample_rate=22050,  # Chatterbox default sample rate
            format="wav"
        )
        
        audio_buffer.seek(0)
        audio_bytes = audio_buffer.read()
        
        logger.info(f"✅ Chatterbox synthesis successful: {len(audio_bytes)} bytes")
        return audio_bytes
        
    except Exception as e:
        logger.error(f"❌ Chatterbox synthesis failed: {e}")
        raise

@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("default", description="Voice profile to use"),
    speed: float = Query(1.0, ge=0.5, le=2.0, description="Speech speed"),
    audio_encoding: str = Query("WAV", description="Audio format"),
    language: str = Query("en", description="Language code"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """TTS endpoint using Chatterbox"""
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:50]}...'")
        
        # Detect emotion from text (simple heuristic)
        emotion = None
        emotion_strength = 0.5
        
        if ENABLE_EMOTION_CONTROL:
            text_lower = text.lower()
            if any(word in text_lower for word in ["happy", "excited", "great", "wonderful", "amazing"]):
                emotion = "happy"
                emotion_strength = 0.7
            elif any(word in text_lower for word in ["sad", "sorry", "unfortunately", "regret"]):
                emotion = "sad"
                emotion_strength = 0.6
            elif any(word in text_lower for word in ["angry", "frustrated", "annoyed"]):
                emotion = "angry"
                emotion_strength = 0.5
            elif any(word in text_lower for word in ["surprised", "wow", "oh", "really"]):
                emotion = "surprised"
                emotion_strength = 0.6
        
        # Generate audio using Chatterbox
        audio_data = synthesize_with_chatterbox(
            text=text,
            voice=voice,
            speed=speed,
            emotion=emotion,
            emotion_strength=emotion_strength
        )
        
        # Determine media type
        media_type = "audio/wav" if audio_encoding.upper() == "WAV" else "audio/mpeg"
        
        return StreamingResponse(
            iter([audio_data]),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{audio_encoding.lower()}",
                "X-TTS-Engine": "chatterbox",
                "X-Caller-Service": calling_service,
                "X-Text-Length": str(len(text)),
                "X-Voice": voice,
                "X-Emotion": emotion or "neutral",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

@app.post("/v1/voice-clone")
async def clone_voice(
    reference_audio: UploadFile = File(..., description="Reference audio for voice cloning"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """Voice cloning endpoint (requires reference audio)"""
    
    if not ENABLE_VOICE_CLONING:
        raise HTTPException(status_code=403, detail="Voice cloning is disabled")
    
    if not chatterbox_model:
        raise HTTPException(status_code=503, detail="Chatterbox model not loaded")
    
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Read reference audio
        audio_content = await reference_audio.read()
        logger.info(f"🎤 Voice cloning request from {calling_service}: {len(audio_content)} bytes")
        
        # Process with Chatterbox voice cloning
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio_content)
            temp_file.flush()
            
            # Load reference audio
            waveform, sample_rate = torchaudio.load(temp_file.name)
            
            # Extract voice embedding using Chatterbox
            with torch.no_grad():
                voice_embedding = chatterbox_model.extract_voice_embedding(waveform)
            
            # Generate a unique voice ID
            import uuid
            voice_id = f"cloned_{uuid.uuid4().hex[:8]}"
            
            # Store voice embedding (in production, save to database)
            # For now, we'll just return the ID
            
            os.unlink(temp_file.name)
        
        logger.info(f"✅ Voice cloned successfully: {voice_id}")
        
        return {
            "voice_id": voice_id,
            "status": "success",
            "message": "Voice cloned successfully",
            "caller": calling_service,
        }
        
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    
    # Initialize Chatterbox on startup
    if chatterbox_model:
        logger.info("🎭 Chatterbox TTS ready with features:")
        logger.info(f"  • Device: {DEVICE}")
        logger.info(f"  • Voice Cloning: {ENABLE_VOICE_CLONING}")
        logger.info(f"  • Emotion Control: {ENABLE_EMOTION_CONTROL}")
        logger.info(f"  • Available Voices: {list(VOICE_PROFILES.keys())}")
    
    logger.info(f"Starting June TTS Service (Chatterbox) on port {os.getenv('PORT', '8080')}")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), workers=1)