"""
ASR Streaming Microservice based on whisper_streaming
FastAPI server with WebSocket support for real-time transcription
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import numpy as np
import logging
import io
import soundfile
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

# These imports will come from whisper_streaming
try:
    from whisper_online import FasterWhisperASR, OnlineASRProcessor, VACOnlineASRProcessor
except ImportError:
    print("Warning: whisper_online not found. Install whisper_streaming package.")
    FasterWhisperASR = None
    OnlineASRProcessor = None
    VACOnlineASRProcessor = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
SAMPLING_RATE = 16000
CHANNELS = 1

app = FastAPI(
    title="ASR Streaming Microservice",
    description="Real-time speech-to-text transcription using Whisper Streaming",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
class ASRConfig(BaseModel):
    model: str = "base"
    language: str = "en"
    task: str = "transcribe"
    use_vac: bool = True
    min_chunk_size: float = 1.0
    vac_chunk_size: float = 0.04
    buffer_trimming: str = "segment"

class ASRService:
    """Manages ASR model and processing"""
    
    def __init__(self, config: ASRConfig):
        self.config = config
        self.asr = None
        self.is_ready = False
        
    async def initialize(self):
        """Initialize the ASR model"""
        if FasterWhisperASR is None:
            raise RuntimeError("whisper_online not installed")
            
        try:
            logger.info(f"Loading Whisper {self.config.model} model for {self.config.language}...")
            
            # Initialize ASR backend
            self.asr = FasterWhisperASR(
                lan=self.config.language,
                modelsize=self.config.model,
                cache_dir=None,
                model_dir=None
            )
            
            # Set task (transcribe or translate)
            if self.config.task == "translate":
                self.asr.set_translate_task()
            
            # Enable VAD if configured
            if self.config.use_vac:
                self.asr.use_vad()
            
            logger.info(f"Model loaded successfully")
            self.is_ready = True
            
            # Warmup with dummy audio
            await self._warmup()
            
        except Exception as e:
            logger.error(f"Failed to initialize ASR: {e}")
            raise
    
    async def _warmup(self):
        """Warm up the model with dummy audio"""
        try:
            logger.info("Warming up ASR model...")
            dummy_audio = np.zeros(SAMPLING_RATE, dtype=np.float32)  # 1 second of silence
            
            if self.config.use_vac:
                processor = VACOnlineASRProcessor(
                    self.asr,
                    self.config.vac_chunk_size,
                    buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size)
                )
            else:
                processor = OnlineASRProcessor(
                    self.asr,
                    buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size)
                )
            
            processor.insert_audio_chunk(dummy_audio)
            list(processor.process_iter())
            processor.finish()
            
            logger.info("ASR model warmed up successfully")
        except Exception as e:
            logger.warning(f"Warmup failed (non-critical): {e}")
    
    def create_processor(self):
        """Create a new ASR processor for a session"""
        if not self.is_ready:
            raise RuntimeError("ASR service not initialized")
        
        if self.config.use_vac:
            return VACOnlineASRProcessor(
                self.asr,
                self.config.vac_chunk_size,
                buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size)
            )
        else:
            return OnlineASRProcessor(
                self.asr,
                buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size)
            )

# Global ASR service instance
asr_service: Optional[ASRService] = None

@app.on_event("startup")
async def startup_event():
    """Initialize ASR service on startup"""
    global asr_service
    
    # Load configuration (can be from env vars)
    config = ASRConfig(
        model="base",  # Can use: tiny, base, small, medium, large-v2, large-v3
        language="en",
        task="transcribe",
        use_vac=True,
        min_chunk_size=1.0,
        vac_chunk_size=0.04
    )
    
    asr_service = ASRService(config)
    await asr_service.initialize()
    logger.info("ASR Microservice started successfully")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "ASR Streaming Microservice",
        "status": "running",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if asr_service and asr_service.is_ready:
        return {
            "status": "healthy",
            "model": asr_service.config.model,
            "language": asr_service.config.language,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        raise HTTPException(status_code=503, detail="Service not ready")

@app.get("/config")
async def get_config():
    """Get current ASR configuration"""
    if not asr_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return {
        "model": asr_service.config.model,
        "language": asr_service.config.language,
        "task": asr_service.config.task,
        "use_vac": asr_service.config.use_vac,
        "min_chunk_size": asr_service.config.min_chunk_size,
        "vac_chunk_size": asr_service.config.vac_chunk_size,
        "sampling_rate": SAMPLING_RATE
    }

@app.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    """
    WebSocket endpoint for real-time transcription
    
    Expected format: Raw PCM audio bytes (16kHz, mono, 16-bit signed integer)
    Returns: JSON with transcription results
    """
    await websocket.accept()
    
    if not asr_service or not asr_service.is_ready:
        await websocket.send_json({"error": "Service not ready"})
        await websocket.close()
        return
    
    logger.info(f"New WebSocket connection established")
    
    # Create a processor for this session
    processor = asr_service.create_processor()
    session_id = id(processor)
    
    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "config": {
                "sampling_rate": SAMPLING_RATE,
                "channels": CHANNELS,
                "format": "PCM_16"
            }
        })
        
        while True:
            # Receive audio data
            data = await websocket.receive_bytes()
            
            if len(data) == 0:
                continue
            
            # Convert bytes to numpy array
            try:
                # Read as PCM 16-bit signed integer
                audio_buffer = io.BytesIO(data)
                sf = soundfile.SoundFile(
                    audio_buffer,
                    channels=CHANNELS,
                    endian="LITTLE",
                    samplerate=SAMPLING_RATE,
                    subtype="PCM_16",
                    format="RAW"
                )
                audio = sf.read(dtype=np.float32)
                
                # Insert audio chunk
                processor.insert_audio_chunk(audio)
                
                # Process and get results
                for output in processor.process_iter():
                    if output[0] is not None:
                        beg, end, text = output
                        
                        result = {
                            "type": "partial",
                            "text": text,
                            "start": float(beg),
                            "end": float(end),
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        
                        await websocket.send_json(result)
                        logger.debug(f"Sent: {text}")
                
            except Exception as e:
                logger.error(f"Error processing audio chunk: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    
    finally:
        # Finalize transcription
        try:
            output = processor.finish()
            if output[0] is not None:
                beg, end, text = output
                await websocket.send_json({
                    "type": "final",
                    "text": text,
                    "start": float(beg),
                    "end": float(end),
                    "timestamp": datetime.utcnow().isoformat()
                })
        except:
            pass
        
        logger.info(f"Session {session_id} closed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")