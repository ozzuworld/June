# services/june-kokoro-tts/app.py
import os
import io
import time
import logging
import asyncio
from typing import Optional, Dict, Any
import tempfile
import subprocess
from pathlib import Path

from fastapi import FastAPI, Query, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
import torch
import torchaudio
import soundfile as sf
import numpy as np

# Import auth modules
from shared.auth_service import require_service_auth

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="June Kokoro TTS", version="1.0.0")

# Global variables for model
kokoro_pipeline = None
available_voices = {}
model_download_lock = asyncio.Lock()

def download_kokoro_model_if_needed():
    """Download Kokoro model if not present"""
    import subprocess
    import sys
    
    try:
        # Run the download script
        result = subprocess.run([sys.executable, "/app/download_model.py"], 
                              capture_output=True, text=True, timeout=300)
        
        # Print output for debugging
        if result.stdout:
            logger.info(f"Model download output: {result.stdout}")
        if result.stderr:
            logger.warning(f"Model download stderr: {result.stderr}")
        
        # Check if required files exist
        model_dir = Path("/app/models")
        required_files = ["config.json", "pytorch_model.bin", "voices.bin"]
        
        missing = []
        for f in required_files:
            file_path = model_dir / f
            if not file_path.exists() or file_path.stat().st_size < 100:
                missing.append(f)
        
        if missing:
            logger.warning(f"⚠️ Missing or small model files: {missing}")
            return False
        
        logger.info("✅ Kokoro model is ready")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("❌ Model download timed out")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to run model download: {e}")
        return False

class KokoroTTSEngine:
    """Kokoro TTS Engine with CPU optimization and auto-download"""
    
    def __init__(self, model_path: str = "/app/models"):
        self.model_path = model_path
        self.device = "cpu"  # Force CPU for reliability
        self.pipeline = None
        self.voices = {}
        self.sample_rate = 24000
        
    async def initialize(self):
        """Initialize the Kokoro model with auto-download"""
        try:
            logger.info("🚀 Initializing Kokoro TTS...")
            
            # Download model if needed
            async with model_download_lock:
                if not download_kokoro_model_if_needed():
                    logger.error("❌ Failed to download Kokoro model")
                    return await self._initialize_fallback()
            
            # Try importing kokoro
            try:
                from kokoro import KPipeline
                logger.info("✅ Kokoro library imported successfully")
            except ImportError as e:
                logger.error(f"❌ Failed to import Kokoro: {e}")
                return await self._initialize_fallback()
            
            # Initialize pipeline with American English
            try:
                self.pipeline = KPipeline(lang_code='a')  # 'a' for American English
                logger.info("✅ Kokoro pipeline initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Kokoro pipeline: {e}")
                return await self._initialize_fallback()
            
            # Load available voices
            self.voices = {
                'af_bella': 'American Female - Bella',
                'af_nicole': 'American Female - Nicole', 
                'af_sarah': 'American Female - Sarah',
                'af_sky': 'American Female - Sky',
                'am_adam': 'American Male - Adam',
                'am_michael': 'American Male - Michael'
            }
            
            logger.info(f"✅ Kokoro TTS initialized with {len(self.voices)} voices")
            logger.info(f"📱 Available voices: {list(self.voices.keys())}")
            
            # Test synthesis
            await self._test_synthesis()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Kokoro TTS: {e}")
            return await self._initialize_fallback()
    
    async def _initialize_fallback(self):
        """Fallback initialization with eSpeak-NG"""
        logger.warning("⚠️ Using eSpeak-NG fallback")
        
        self.voices = {
            'af_bella': 'eSpeak Female Voice',
            'cpu_voice': 'CPU Optimized Voice'
        }
        
        logger.info("✅ Fallback TTS mode initialized")
        return True
    
    async def _test_synthesis(self):
        """Test synthesis to ensure everything works"""
        try:
            test_text = "Hello, this is a test of Kokoro TTS."
            audio_data = await self.synthesize(test_text, voice="af_bella")
            
            if audio_data and len(audio_data) > 1000:
                logger.info("✅ Synthesis test passed")
            else:
                logger.warning("⚠️ Synthesis test produced short audio")
                
        except Exception as e:
            logger.error(f"❌ Synthesis test failed: {e}")
    
    async def synthesize(
        self,
        text: str,
        voice: str = "af_bella",
        speed: float = 1.0,
        output_format: str = "wav"
    ) -> Optional[bytes]:
        """Synthesize speech from text"""
        try:
            logger.info(f"🎵 Synthesizing: '{text[:50]}...' with voice '{voice}'")
            
            if not self.pipeline:
                # Use fallback synthesis
                return await self._fallback_synthesis(text, voice, speed, output_format)
            
            # Use Kokoro pipeline
            generator = self.pipeline(text, voice=voice)
            
            # Collect all audio chunks
            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(generator):
                if audio is not None and len(audio) > 0:
                    audio_chunks.append(audio)
                    
                # Limit to prevent infinite loops
                if i > 100:
                    break
            
            if not audio_chunks:
                logger.error("❌ No audio generated")
                return await self._fallback_synthesis(text, voice, speed, output_format)
            
            # Concatenate audio chunks
            full_audio = np.concatenate(audio_chunks)
            
            # Apply speed adjustment
            if speed != 1.0:
                full_audio = self._adjust_speed(full_audio, speed)
            
            # Convert to output format
            return await self._convert_audio(full_audio, output_format)
            
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            return await self._fallback_synthesis(text, voice, speed, output_format)
    
    async def _fallback_synthesis(
        self,
        text: str,
        voice: str,
        speed: float,
        output_format: str
    ) -> Optional[bytes]:
        """Fallback synthesis using eSpeak-NG"""
        try:
            logger.info("🔧 Using eSpeak-NG fallback synthesis")
            
            # Use eSpeak-NG with better voice settings
            espeak_cmd = [
                "espeak-ng",
                "-v", "en+f3",  # Female voice variant
                "-s", str(int(150 * speed)),  # Speed (words per minute)
                "-a", "100",  # Amplitude
                "-g", "5",    # Gap between words
                "--stdout",
                text
            ]
            
            # Run eSpeak-NG
            result = subprocess.run(
                espeak_cmd,
                capture_output=True,
                check=True
            )
            
            audio_data = result.stdout
            
            if output_format.lower() == "mp3":
                # Convert WAV to MP3 using ffmpeg
                return await self._convert_wav_to_mp3(audio_data)
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ Fallback synthesis failed: {e}")
            return None
    
    def _adjust_speed(self, audio: np.ndarray, speed: float) -> np.ndarray:
        """Adjust audio speed"""
        if speed == 1.0:
            return audio
        
        try:
            # Simple speed adjustment by resampling
            from scipy import signal
            new_length = int(len(audio) / speed)
            return signal.resample(audio, new_length)
        except Exception:
            logger.warning("⚠️ Speed adjustment failed, using original audio")
            return audio
    
    async def _convert_audio(self, audio: np.ndarray, output_format: str) -> bytes:
        """Convert audio to requested format"""
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{output_format}") as temp_file:
                if output_format.lower() == "wav":
                    sf.write(temp_file.name, audio, self.sample_rate)
                elif output_format.lower() == "mp3":
                    # Save as WAV first, then convert
                    wav_file = temp_file.name.replace(".mp3", ".wav")
                    sf.write(wav_file, audio, self.sample_rate)
                    await self._convert_wav_to_mp3_file(wav_file, temp_file.name)
                
                temp_file.seek(0)
                return temp_file.read()
                
        except Exception as e:
            logger.error(f"❌ Audio conversion failed: {e}")
            # Return raw audio as bytes
            return audio.astype(np.float32).tobytes()
    
    async def _convert_wav_to_mp3(self, wav_data: bytes) -> bytes:
        """Convert WAV data to MP3"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:
                with tempfile.NamedTemporaryFile(suffix=".mp3") as mp3_file:
                    wav_file.write(wav_data)
                    wav_file.flush()
                    
                    # Use ffmpeg to convert
                    cmd = [
                        "ffmpeg", "-i", wav_file.name,
                        "-acodec", "mp3", "-ab", "128k",
                        "-y", mp3_file.name
                    ]
                    
                    subprocess.run(cmd, capture_output=True, check=True)
                    
                    mp3_file.seek(0)
                    return mp3_file.read()
                    
        except Exception as e:
            logger.error(f"❌ WAV to MP3 conversion failed: {e}")
            return wav_data  # Return original if conversion fails
    
    async def _convert_wav_to_mp3_file(self, wav_path: str, mp3_path: str):
        """Convert WAV file to MP3 file"""
        cmd = [
            "ffmpeg", "-i", wav_path,
            "-acodec", "mp3", "-ab", "128k", 
            "-y", mp3_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)

# Initialize the TTS engine
@app.on_event("startup")
async def startup_event():
    """Initialize TTS engine on startup"""
    global kokoro_pipeline, available_voices
    
    logger.info("🚀 Starting Kokoro TTS service...")
    
    kokoro_pipeline = KokoroTTSEngine()
    success = await kokoro_pipeline.initialize()
    
    if success:
        available_voices = kokoro_pipeline.voices
        logger.info("✅ Kokoro TTS service ready")
    else:
        logger.error("❌ Failed to initialize Kokoro TTS")
        available_voices = {"fallback": "eSpeak-NG Fallback"}

# Health check endpoint
@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    model_status = "kokoro" if kokoro_pipeline and kokoro_pipeline.pipeline else "espeak-fallback"
    return {
        "ok": True,
        "service": "june-kokoro-tts",
        "timestamp": time.time(),
        "status": "healthy",
        "engine": model_status,
        "voices_available": len(available_voices),
        "model_path": "/app/models"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-kokoro-tts",
        "status": "running",
        "engine": "kokoro-cpu-optimized",
        "voices": list(available_voices.keys())
    }

@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    return {
        "voices": available_voices,
        "default": "af_bella",
        "engine": "kokoro"
    }

# Service-to-Service TTS Endpoint
@app.post("/v1/tts")
async def synthesize_speech_service(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query("af_bella", description="Voice to use"),
    speed: float = Query(1.0, description="Speech speed (0.5-2.0)"),
    audio_encoding: str = Query("MP3", description="Audio format: MP3 or WAV"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    TTS endpoint for service-to-service communication
    Protected by service authentication
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    
    try:
        # Validate input
        if len(text) > 5000:
            raise HTTPException(status_code=400, detail="Text too long (max 5000 characters)")
        
        if speed < 0.5 or speed > 2.0:
            raise HTTPException(status_code=400, detail="Speed must be between 0.5 and 2.0")
        
        if voice not in available_voices and voice != "default":
            logger.warning(f"Voice '{voice}' not available, using default")
            voice = "af_bella"
        
        logger.info(f"🎵 TTS request from {calling_service}: '{text[:100]}...' ({len(text)} chars)")
        
        # Synthesize speech
        audio_data = await kokoro_pipeline.synthesize(
            text=text,
            voice=voice,
            speed=speed,
            output_format=audio_encoding.lower()
        )
        
        if not audio_data:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
        
        # Determine media type
        if audio_encoding.upper() == "MP3":
            media_type = "audio/mpeg"
            ext = "mp3"
        else:
            media_type = "audio/wav" 
            ext = "wav"
        
        logger.info(f"✅ TTS successful: {len(audio_data)} bytes generated for {calling_service}")
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{ext}",
                "X-Processed-By": "june-kokoro-tts",
                "X-Caller-Service": calling_service,
                "X-Voice-Used": voice,
                "X-Engine": "kokoro-cpu"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

# Test endpoint (for debugging)
@app.get("/v1/test")
async def test_synthesis(
    text: str = Query("Hello, this is a test of Kokoro TTS running on CPU."),
    voice: str = Query("af_bella")
):
    """Test endpoint for direct synthesis testing"""
    try:
        audio_data = await kokoro_pipeline.synthesize(text, voice)
        
        if audio_data:
            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/wav",
                headers={"X-Test": "kokoro-tts"}
            )
        else:
            return JSONResponse(
                status_code=500,
                content={"error": "Synthesis failed", "text": text}
            )
            
    except Exception as e:
        logger.error(f"Test synthesis failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "text": text}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)