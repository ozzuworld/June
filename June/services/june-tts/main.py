# June/services/june-tts/main.py - Enhanced TTS with Voice Cloning
"""
Enhanced TTS service with comprehensive voice cloning capabilities
- Voice cloning from reference audio files
- Voice management (upload, store, reuse)
- Speaker caching for performance
- Cross-language voice cloning
- Real-time processing optimization
"""
import os
import torch
import logging
import base64
import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
import tempfile
import librosa
import soundfile as sf
import numpy as np
from TTS.api import TTS

# Import LiveKit participant
from livekit_participant import get_tts_participant, TTSRoomParticipant

# Accept Coqui TTS license
os.environ['COQUI_TOS_AGREED'] = '1'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June TTS Service - Voice Cloning Enhanced",
    description="""
    Advanced TTS service with comprehensive voice cloning capabilities:
    
    ## Features
    - **Built-in Voices**: 58 pre-trained speaker voices in 17 languages
    - **Voice Cloning**: Clone any voice from 6+ seconds of audio
    - **Voice Management**: Upload, store, and reuse custom voices
    - **Cross-Language**: Clone voice in one language, speak in another
    - **Real-time Processing**: ~200ms latency for live applications
    - **LiveKit Integration**: Direct audio publishing to rooms
    
    ## Voice Cloning Requirements
    - **Minimum Duration**: 6 seconds (10+ seconds recommended)
    - **Audio Format**: WAV, MP3, FLAC, or M4A
    - **Sample Rate**: 16-48kHz (will be resampled to 24kHz)
    - **Quality**: Clear speech, minimal background noise
    - **Content**: Single speaker only
    - **Multiple Files**: Supported for better voice quality
    
    ## Supported Languages
    English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, 
    Russian, Dutch, Czech, Arabic, Chinese, Japanese, Hungarian, Korean, Hindi
    """,
    version="4.0.0"
)

# Global TTS instance and voice cache
tts_instance = None
device = "cuda" if torch.cuda.is_available() else "cpu"
tts_ready = False

# Voice management
VOICES_DIR = Path("/app/voices")
CACHE_DIR = Path("/app/cache")
voice_cache: Dict[str, Dict[str, Any]] = {}

# Ensure directories exist
VOICES_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)


class TTSRequest(BaseModel):
    """Basic TTS request with built-in speakers"""
    text: str = Field(..., description="Text to synthesize", max_length=5000)
    language: str = Field("en", description="Language code (e.g., 'en', 'es', 'fr')")
    speaker: Optional[str] = Field(None, description="Built-in speaker name")
    speed: float = Field(1.0, description="Speech speed multiplier", ge=0.5, le=2.0)

    @validator('text')
    def validate_text(cls, v):
        if not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()


class VoiceCloneRequest(BaseModel):
    """Voice cloning request with reference audio"""
    text: str = Field(..., description="Text to synthesize", max_length=5000)
    language: str = Field("en", description="Target language for synthesis")
    voice_id: Optional[str] = Field(None, description="Stored voice ID to use")
    speed: float = Field(1.0, description="Speech speed multiplier", ge=0.5, le=2.0)
    
    @validator('text')
    def validate_text(cls, v):
        if not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()


class PublishToRoomRequest(BaseModel):
    """Request to publish TTS audio to LiveKit room"""
    room_name: str = Field(..., description="LiveKit room name")
    text: str = Field(..., description="Text to synthesize", max_length=5000)
    language: str = Field("en", description="Language code")
    speaker: Optional[str] = Field(None, description="Built-in speaker name")
    voice_id: Optional[str] = Field(None, description="Custom voice ID")
    speed: float = Field(1.0, description="Speech speed multiplier", ge=0.5, le=2.0)


class VoiceInfo(BaseModel):
    """Voice information response"""
    voice_id: str
    name: str
    language: str
    description: Optional[str]
    duration: float
    created_at: str
    file_count: int
    sample_rate: int
    is_cached: bool


def validate_audio_file(file: UploadFile) -> Dict[str, Any]:
    """
    Validate uploaded audio file meets XTTS-v2 requirements
    
    Returns:
        Dict with validation results and metadata
    """
    if not file.content_type or not file.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be audio format")
    
    # Supported formats
    supported_formats = ['audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/flac', 'audio/x-wav']
    if file.content_type not in supported_formats:
        # Try by filename extension
        if not any(file.filename.lower().endswith(ext) for ext in ['.wav', '.mp3', '.flac', '.m4a', '.mp4']):
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported audio format. Supported: WAV, MP3, FLAC, M4A"
            )
    
    # Save to temp file for analysis
    with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
        content = file.file.read()
        temp_file.write(content)
        temp_path = temp_file.name
        file.file.seek(0)  # Reset for potential reuse
    
    try:
        # Load and analyze audio
        audio, sample_rate = librosa.load(temp_path, sr=None)
        duration = len(audio) / sample_rate
        
        # Validation checks
        if duration < 6.0:
            raise HTTPException(
                status_code=400, 
                detail=f"Audio too short: {duration:.1f}s. Minimum 6 seconds required, 10+ recommended."
            )
        
        if duration > 300.0:  # 5 minutes max
            raise HTTPException(
                status_code=400,
                detail=f"Audio too long: {duration:.1f}s. Maximum 300 seconds allowed."
            )
        
        if sample_rate < 16000:
            raise HTTPException(
                status_code=400,
                detail=f"Sample rate too low: {sample_rate}Hz. Minimum 16kHz required."
            )
        
        # Convert to 24kHz mono for XTTS-v2
        if sample_rate != 24000:
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=24000)
            sample_rate = 24000
        
        # Ensure mono
        if len(audio.shape) > 1:
            audio = librosa.to_mono(audio)
        
        # Normalize audio
        audio = librosa.util.normalize(audio)
        
        # Save processed audio
        processed_path = temp_path.replace('.wav', '_processed.wav')
        sf.write(processed_path, audio, sample_rate)
        
        # Clean up original
        os.unlink(temp_path)
        
        return {
            'processed_path': processed_path,
            'duration': duration,
            'sample_rate': sample_rate,
            'channels': 1,
            'valid': True
        }
        
    except Exception as e:
        # Cleanup on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=400, detail=f"Audio processing failed: {str(e)}")


def generate_voice_id(files: List[UploadFile], name: str) -> str:
    """Generate unique voice ID from files and name"""
    content_hash = hashlib.md5()
    content_hash.update(name.encode())
    
    for file in files:
        file.file.seek(0)
        content_hash.update(file.file.read())
        file.file.seek(0)
    
    return content_hash.hexdigest()[:16]


def load_voice_cache():
    """Load voice cache from disk"""
    global voice_cache
    cache_file = CACHE_DIR / "voice_cache.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                voice_cache = json.load(f)
            logger.info(f"Loaded {len(voice_cache)} cached voices")
        except Exception as e:
            logger.warning(f"Failed to load voice cache: {e}")
            voice_cache = {}


def save_voice_cache():
    """Save voice cache to disk"""
    cache_file = CACHE_DIR / "voice_cache.json"
    try:
        with open(cache_file, 'w') as f:
            json.dump(voice_cache, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save voice cache: {e}")


@app.on_event("startup")
async def startup_event():
    global tts_instance, tts_ready
    logger.info(f"🚀 Initializing TTS on device: {device}")
    
    # Initialize XTTS-v2 model
    tts_instance = TTS(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        gpu=torch.cuda.is_available()
    ).to(device)
    
    # Load voice cache
    load_voice_cache()
    
    tts_ready = True
    logger.info("✅ TTS instance initialized with voice cloning support")
    
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
        "device": device,
        "voice_cloning": True,
        "cached_voices": len(voice_cache),
        "features": [
            "built-in speakers",
            "voice cloning",
            "cross-language synthesis",
            "speaker caching",
            "livekit integration"
        ]
    }


@app.post("/synthesize-binary")
async def synthesize_speech_binary(request: TTSRequest):
    """
    Traditional TTS endpoint with built-in speakers
    Returns audio bytes directly
    """
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        speaker_to_use = request.speaker or "Claribel Dervla"
        
        logger.info(f"🎙️ Synthesizing with speaker '{speaker_to_use}': {request.text[:50]}...")
        
        # Generate audio with built-in speaker
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
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=speech.wav"}
        )
        
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clone-voice")
async def clone_voice_endpoint(
    files: List[UploadFile] = File(..., description="Reference audio files (6+ seconds each)"),
    name: str = Form(..., description="Voice name for identification"),
    description: str = Form("", description="Optional voice description"),
    language: str = Form("en", description="Primary language of reference audio")
):
    """
    Upload and store a custom voice for cloning
    
    **Requirements:**
    - Minimum 6 seconds per file (10+ recommended)
    - Clear speech, single speaker
    - WAV, MP3, FLAC, or M4A format
    - Multiple files supported for better quality
    
    **Returns:** Voice ID for use in synthesis requests
    """
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    
    if not files:
        raise HTTPException(status_code=400, detail="At least one audio file required")
    
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 reference files allowed")
    
    try:
        # Generate voice ID
        voice_id = generate_voice_id(files, name)
        
        # Check if voice already exists
        if voice_id in voice_cache:
            logger.info(f"Voice '{name}' already exists with ID: {voice_id}")
            return {"voice_id": voice_id, "status": "exists", "message": "Voice already stored"}
        
        # Validate and process each file
        processed_files = []
        total_duration = 0
        
        for i, file in enumerate(files):
            logger.info(f"Processing file {i+1}/{len(files)}: {file.filename}")
            validation = validate_audio_file(file)
            processed_files.append(validation['processed_path'])
            total_duration += validation['duration']
        
        # Create voice directory
        voice_dir = VOICES_DIR / voice_id
        voice_dir.mkdir(exist_ok=True)
        
        # Move processed files to voice directory
        final_paths = []
        for i, processed_path in enumerate(processed_files):
            final_path = voice_dir / f"reference_{i}.wav"
            os.rename(processed_path, str(final_path))
            final_paths.append(str(final_path))
        
        # Store voice metadata
        from datetime import datetime
        voice_info = {
            "voice_id": voice_id,
            "name": name,
            "description": description,
            "language": language,
            "files": final_paths,
            "duration": total_duration,
            "file_count": len(final_paths),
            "sample_rate": 24000,
            "created_at": datetime.now().isoformat(),
            "is_cached": True
        }
        
        # Add to cache
        voice_cache[voice_id] = voice_info
        save_voice_cache()
        
        logger.info(f"✅ Voice '{name}' stored with ID: {voice_id}")
        
        return {
            "voice_id": voice_id,
            "name": name,
            "status": "created",
            "duration": total_duration,
            "file_count": len(final_paths),
            "message": "Voice successfully cloned and stored"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning error: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")


@app.post("/synthesize-clone")
async def synthesize_with_cloned_voice(
    request: VoiceCloneRequest,
    files: Optional[List[UploadFile]] = File(None, description="Optional: Reference audio for one-time cloning")
):
    """
    Synthesize speech using a cloned voice
    
    **Options:**
    1. Use stored voice: Provide `voice_id` from `/clone-voice`
    2. One-time cloning: Upload reference files directly
    
    **Cross-language support:** Clone voice in one language, synthesize in another
    """
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    
    try:
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        reference_files = []
        
        # Option 1: Use stored voice
        if request.voice_id:
            if request.voice_id not in voice_cache:
                raise HTTPException(status_code=404, detail=f"Voice ID '{request.voice_id}' not found")
            
            voice_info = voice_cache[request.voice_id]
            reference_files = voice_info["files"]
            logger.info(f"🎭 Using stored voice: {voice_info['name']} ({request.voice_id})")
        
        # Option 2: One-time cloning
        elif files:
            logger.info("🎭 Processing one-time voice cloning")
            processed_files = []
            
            for file in files:
                validation = validate_audio_file(file)
                processed_files.append(validation['processed_path'])
            
            reference_files = processed_files
        
        else:
            raise HTTPException(status_code=400, detail="Either voice_id or reference files required")
        
        logger.info(f"🎙️ Cloning voice for text: {request.text[:50]}...")
        logger.info(f"🌍 Target language: {request.language}")
        
        # Generate audio with voice cloning
        tts_instance.tts_to_file(
            text=request.text,
            file_path=output_path,
            speaker_wav=reference_files,
            language=request.language,
            speed=request.speed
        )
        
        # Read audio bytes
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        
        # Cleanup
        os.unlink(output_path)
        if not request.voice_id and files:  # Clean up one-time files
            for temp_file in reference_files:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=cloned_speech.wav"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/publish-to-room")
async def publish_to_room(
    request: PublishToRoomRequest,
    background_tasks: BackgroundTasks
):
    """
    Publish TTS audio directly to LiveKit room
    
    **Supports:**
    - Built-in speakers (use `speaker` field)
    - Cloned voices (use `voice_id` field)
    - Cross-language synthesis
    - Real-time processing (~200ms latency)
    """
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    
    try:
        logger.info(f"🔊 Publishing to room: {request.room_name}")
        logger.info(f"📝 Text: {request.text[:100]}...")
        
        # Generate audio
        output_path = f"/tmp/{uuid.uuid4()}.wav"
        
        # Choose synthesis method
        if request.voice_id:
            # Use cloned voice
            if request.voice_id not in voice_cache:
                raise HTTPException(status_code=404, detail=f"Voice ID '{request.voice_id}' not found")
            
            voice_info = voice_cache[request.voice_id]
            reference_files = voice_info["files"]
            logger.info(f"🎭 Using cloned voice: {voice_info['name']}")
            
            tts_instance.tts_to_file(
                text=request.text,
                file_path=output_path,
                speaker_wav=reference_files,
                language=request.language,
                speed=request.speed
            )
        else:
            # Use built-in speaker
            speaker_to_use = request.speaker or "Claribel Dervla"
            logger.info(f"🎙️ Using built-in speaker: {speaker_to_use}")
            
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
            "synthesis_type": "cloned" if request.voice_id else "built-in",
            "message": "Audio publishing to room"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Publish to room error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/voices", response_model=Dict[str, List[VoiceInfo]])
async def list_voices():
    """
    List all available voices (built-in and custom)
    
    **Returns:**
    - Built-in speakers (58 preloaded voices)
    - Custom cloned voices with metadata
    """
    # Built-in speakers
    builtin_speakers = [
        "Claribel Dervla", "Daisy Studious", "Gracie Wise", "Andrew Chipper", 
        "Badr Odhiambo", "Antoni Ramirez", "Thomas Pearce", "Gilberto Mathias",
        "Brenda Meaney", "Tammie Ema", "Alison Dietlinde", "Ana Florence"
    ]
    
    builtin_voices = []
    for speaker in builtin_speakers:
        builtin_voices.append(VoiceInfo(
            voice_id=f"builtin_{speaker.lower().replace(' ', '_')}",
            name=speaker,
            language="multilingual",
            description=f"Built-in XTTS-v2 speaker: {speaker}",
            duration=0.0,
            created_at="2023-10-30T00:00:00",
            file_count=1,
            sample_rate=24000,
            is_cached=True
        ))
    
    # Custom voices
    custom_voices = []
    for voice_id, voice_info in voice_cache.items():
        custom_voices.append(VoiceInfo(
            voice_id=voice_id,
            name=voice_info["name"],
            language=voice_info["language"],
            description=voice_info.get("description", ""),
            duration=voice_info["duration"],
            created_at=voice_info["created_at"],
            file_count=voice_info["file_count"],
            sample_rate=voice_info["sample_rate"],
            is_cached=True
        ))
    
    return {
        "builtin_voices": builtin_voices,
        "custom_voices": custom_voices,
        "summary": {
            "total_voices": len(builtin_voices) + len(custom_voices),
            "builtin_count": len(builtin_voices),
            "custom_count": len(custom_voices)
        }
    }


@app.get("/voices/{voice_id}")
async def get_voice_info(voice_id: str):
    """Get detailed information about a specific voice"""
    if voice_id not in voice_cache:
        raise HTTPException(status_code=404, detail=f"Voice ID '{voice_id}' not found")
    
    return voice_cache[voice_id]


@app.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a custom voice and its files"""
    if voice_id not in voice_cache:
        raise HTTPException(status_code=404, detail=f"Voice ID '{voice_id}' not found")
    
    try:
        voice_info = voice_cache[voice_id]
        
        # Delete voice files
        voice_dir = VOICES_DIR / voice_id
        if voice_dir.exists():
            import shutil
            shutil.rmtree(voice_dir)
        
        # Remove from cache
        del voice_cache[voice_id]
        save_voice_cache()
        
        logger.info(f"🗑️ Deleted voice: {voice_info['name']} ({voice_id})")
        
        return {
            "status": "deleted",
            "voice_id": voice_id,
            "name": voice_info["name"],
            "message": "Voice successfully deleted"
        }
        
    except Exception as e:
        logger.error(f"❌ Delete voice error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete voice: {str(e)}")


@app.get("/languages")
async def get_supported_languages():
    """Get list of supported languages for synthesis"""
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
        "zh-cn": "Chinese (Simplified)",
        "ja": "Japanese",
        "hu": "Hungarian",
        "ko": "Korean",
        "hi": "Hindi"
    }
    
    return {
        "supported_languages": languages,
        "total_languages": len(languages),
        "cross_language_cloning": True,
        "note": "You can clone a voice in one language and synthesize speech in any supported language"
    }


# Legacy endpoint for backward compatibility
@app.get("/speakers")
async def get_speakers():
    """Legacy endpoint - use /voices for comprehensive voice listing"""
    speakers = [
        "Claribel Dervla", "Daisy Studious", "Gracie Wise",
        "Andrew Chipper", "Badr Odhiambo"
    ]
    return {
        "speakers": speakers,
        "default": "Claribel Dervla",
        "note": "Use /voices endpoint for complete voice listing including custom voices"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)