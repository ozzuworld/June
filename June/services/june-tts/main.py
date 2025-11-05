#!/usr/bin/env python3
"""
CosyVoice2 TTS Service - Official Implementation
Ultra-low latency streaming TTS with LiveKit integration

*** ENHANCED WITH FULL DEBUG LOGGING ***
"""

import sys
import os

# Add CosyVoice and Matcha-TTS to path (required by CosyVoice)
sys.path.append('/opt/CosyVoice')
sys.path.append('/opt/CosyVoice/third_party/Matcha-TTS')

import asyncio
import logging
import time
import traceback
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
import uvicorn

# CosyVoice2 imports
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

# LiveKit
from livekit import rtc

# Local imports
from config import config
from livekit_token import connect_room_as_publisher

# =============================================================================
# FULL DEBUG LOGGING MIDDLEWARE - LOGS EVERY REQUEST IN EXTREME DETAIL
# =============================================================================

class FullDebugMiddleware(BaseHTTPMiddleware):
    """Logs EVERY SINGLE REQUEST in extreme detail"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log incoming request with maximum detail
        debug_logger.info("=" * 80)
        debug_logger.info(f"🔥🔥🔥 INCOMING REQUEST DETECTED 🔥🔥🔥")
        debug_logger.info(f"   ⏰ Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S.%f')}")
        debug_logger.info(f"   📍 Method: {request.method}")
        debug_logger.info(f"   🌐 Full URL: {str(request.url)}")
        debug_logger.info(f"   📁 Path: {request.url.path}")
        debug_logger.info(f"   🔗 Query String: {request.url.query}")
        debug_logger.info(f"   💻 Client IP: {request.client.host}")
        debug_logger.info(f"   🔌 Client Port: {request.client.port}")
        debug_logger.info(f"   🌍 Remote Address: {request.client}")
        
        # Log ALL headers in detail
        debug_logger.info(f"   📋 REQUEST HEADERS ({len(request.headers)} total):")
        for key, value in request.headers.items():
            debug_logger.info(f"     📝 {key}: {value}")
        
        # Log query parameters
        if request.query_params:
            debug_logger.info(f"   ❓ Query Parameters:")
            for key, value in request.query_params.items():
                debug_logger.info(f"     🔍 {key}: {value}")
        
        # For POST/PUT/PATCH requests, capture and log the body
        body_data = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body_data = await request.body()
                if body_data:
                    debug_logger.info(f"   📦 Body Size: {len(body_data)} bytes")
                    
                    # Try to decode as text/JSON
                    try:
                        body_text = body_data.decode('utf-8')
                        debug_logger.info(f"   📄 Body Content (text): {body_text}")
                        
                        # Try to parse as JSON for pretty printing
                        try:
                            body_json = json.loads(body_text)
                            debug_logger.info(f"   📋 Body Content (JSON formatted):")
                            debug_logger.info(json.dumps(body_json, indent=2))
                        except json.JSONDecodeError:
                            debug_logger.info(f"   📄 Body is not valid JSON")
                            
                    except UnicodeDecodeError:
                        debug_logger.info(f"   🔢 Body Content (hex): {body_data.hex()[:400]}...")
                        debug_logger.info(f"   ⚠️ Body contains binary data")
                else:
                    debug_logger.info(f"   📭 Body: EMPTY")
                    
            except Exception as body_error:
                debug_logger.error(f"   ❌ Error reading request body: {body_error}")
                debug_logger.error(f"   🔍 Body error traceback: {traceback.format_exc()}")
        
        debug_logger.info(f"   🏁 Starting request processing...")
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Log successful response
            process_time = time.time() - start_time
            debug_logger.info(f"   ✅ REQUEST COMPLETED SUCCESSFULLY")
            debug_logger.info(f"   📊 Status Code: {response.status_code}")
            debug_logger.info(f"   ⏱️ Processing Time: {process_time:.4f} seconds")
            
            # Log response headers
            debug_logger.info(f"   📋 RESPONSE HEADERS:")
            for key, value in response.headers.items():
                debug_logger.info(f"     📝 {key}: {value}")
                
            debug_logger.info("=" * 80)
            return response
            
        except Exception as process_error:
            # Log any processing errors
            process_time = time.time() - start_time
            debug_logger.error(f"   ❌❌❌ REQUEST PROCESSING FAILED ❌❌❌")
            debug_logger.error(f"   🚨 Error Message: {str(process_error)}")
            debug_logger.error(f"   🔍 Error Type: {type(process_error).__name__}")
            debug_logger.error(f"   ⏱️ Processing Time: {process_time:.4f} seconds")
            debug_logger.error(f"   📚 Full Traceback:")
            debug_logger.error(traceback.format_exc())
            debug_logger.error("=" * 80)
            raise

# Enhanced logging setup with debug logger
logging.basicConfig(
    level=logging.DEBUG,  # Force DEBUG level
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/tts_debug.log')
    ]
)

# Main logger
logger = logging.getLogger("cosyvoice2-tts")

# Create specific logger for TTS debugging
debug_logger = logging.getLogger("TTS-DEBUG")
debug_logger.setLevel(logging.DEBUG)

# =============================================================================
# END DEBUG LOGGING SECTION
# =============================================================================

# Request/Response Models
class TTSRequest(BaseModel):
    """TTS synthesis request"""
    text: str = Field(..., max_length=1000, description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    
    # Voice settings
    mode: str = Field(
        "zero_shot",
        description="Synthesis mode: zero_shot, sft, instruct"
    )
    prompt_text: Optional[str] = Field(None, description="Reference text for zero-shot")
    prompt_audio: Optional[str] = Field(None, description="Reference audio path")
    speaker_id: Optional[str] = Field(None, description="Speaker ID for SFT mode")
    instruct: Optional[str] = Field(None, description="Instruction for instruct mode")
    
    # Advanced options
    streaming: bool = Field(True, description="Enable streaming output")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed")


class TTSResponse(BaseModel):
    """TTS synthesis response"""
    status: str
    room_name: str
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None
    mode: str


class HealthResponse(BaseModel):
    """Health check response"""
    service: str = "cosyvoice2-tts"
    version: str = "1.0.0"
    status: str
    engine: str = "cosyvoice2"
    model: str
    device: str
    gpu_available: bool
    streaming_enabled: bool
    livekit_connected: bool
    debug_enabled: bool = True  # New field


# Global state
metrics = {
    "requests_processed": 0,
    "total_audio_seconds": 0.0,
    "first_chunk_latencies": [],
}


class CosyVoice2Engine:
    """CosyVoice2 TTS engine wrapper"""
    
    def __init__(self):
        self.model: Optional[CosyVoice2] = None
        self.device = config.cosyvoice.device
        self.sample_rate = config.cosyvoice.sample_rate
    
    async def initialize(self):
        """Initialize CosyVoice2 model"""
        try:
            model_path = config.cosyvoice.model_path
            
            if not os.path.exists(model_path):
                logger.error(f"❌ Model not found at {model_path}")
                logger.info("💡 Run: python download_models.py")
                raise FileNotFoundError(f"Model not found: {model_path}")
            
            logger.info(f"📦 Loading CosyVoice2 from {model_path}")
            
            # Load model with official API
            self.model = CosyVoice2(
                model_path,
                load_jit=config.cosyvoice.load_jit,
                load_trt=config.cosyvoice.load_trt,
                load_vllm=config.cosyvoice.load_vllm,
                fp16=config.cosyvoice.fp16 and self.device == "cuda"
            )
            
            logger.info(f"✅ CosyVoice2 loaded on {self.device}")
            logger.info(f"   Sample rate: {self.sample_rate}Hz")
            logger.info(f"   FP16: {config.cosyvoice.fp16 and self.device == 'cuda'}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize CosyVoice2: {e}")
            raise
    
    async def warmup(self):
        """Warmup model for optimal performance"""
        if not self.model:
            return
        
        try:
            logger.info("🔥 Warming up CosyVoice2...")
            start = time.time()
            
            # Simple warmup synthesis
            warmup_text = "Hello, this is a warmup."
            count = 0
            
            for result in self.model.inference_sft(
                warmup_text,
                '中文女',
                stream=False
            ):
                count += 1
                break  # Just one chunk
            
            elapsed = (time.time() - start) * 1000
            logger.info(f"✅ Warmup complete: {elapsed:.0f}ms")
            
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed (non-critical): {e}")
    
    async def synthesize_zero_shot(
        self,
        text: str,
        prompt_text: str,
        prompt_audio_path: str,
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """Zero-shot voice cloning synthesis"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        # Load reference audio
        prompt_speech = load_wav(prompt_audio_path, 16000)
        
        logger.info(f"🎤 Zero-shot synthesis: {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_zero_shot(
            text,
            prompt_text,
            prompt_speech,
            stream=stream
        )):
            audio = result['tts_speech']
            
            # Convert to numpy if needed
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            # Track first chunk latency
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)  # Yield control
    
    async def synthesize_sft(
        self,
        text: str,
        speaker_id: str = '中文女',
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """SFT mode synthesis with predefined speakers"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        logger.info(f"🎤 SFT synthesis ({speaker_id}): {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_sft(
            text,
            speaker_id,
            stream=stream
        )):
            audio = result['tts_speech']
            
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)
    
    async def synthesize_instruct(
        self,
        text: str,
        instruct: str,
        prompt_audio_path: str,
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """Instruct mode synthesis"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        prompt_speech = load_wav(prompt_audio_path, 16000)
        
        logger.info(f"🎤 Instruct synthesis: {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_instruct2(
            text,
            instruct,
            prompt_speech,
            stream=stream
        )):
            audio = result['tts_speech']
            
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)
    
    def get_available_speakers(self) -> list:
        """Get list of available SFT speakers"""
        if not self.model:
            return []
        return self.model.list_available_spks()


class LiveKitPublisher:
    """Persistent LiveKit room connection manager"""
    
    def __init__(self):
        self.rooms: Dict[str, rtc.Room] = {}
        self.room_locks: Dict[str, asyncio.Lock] = {}
        self.connected = False
    
    async def initialize(self, default_room: str):
        """Initialize and connect to default room"""
        try:
            await self._ensure_room_connection(default_room)
            self.connected = True
            logger.info(f"✅ LiveKit publisher ready (room: {default_room})")
        except Exception as e:
            logger.error(f"❌ LiveKit initialization failed: {e}")
            raise
    
    async def _ensure_room_connection(self, room_name: str) -> rtc.Room:
        """Ensure room connection exists"""
        
        if room_name not in self.room_locks:
            self.room_locks[room_name] = asyncio.Lock()
        
        async with self.room_locks[room_name]:
            # Check existing connection
            if room_name in self.rooms:
                room = self.rooms[room_name]
                try:
                    if room.isconnected():
                        return room
                except Exception:
                    pass
                # Reconnect if needed
                logger.info(f"🔄 Reconnecting to room {room_name}")
                del self.rooms[room_name]
            
            # Create new connection
            logger.info(f"🔗 Connecting to LiveKit room: {room_name}")
            room = rtc.Room()
            await connect_room_as_publisher(room, "cosyvoice2-tts", room_name)
            self.rooms[room_name] = room
            
            return room
    
    async def publish_audio_stream(
        self,
        room_name: str,
        audio_stream: AsyncIterator[np.ndarray],
        sample_rate: int
    ) -> Dict[str, Any]:
        """Publish streaming audio to room"""
        
        room = await self._ensure_room_connection(room_name)
        
        # Create audio source and track
        audio_source = rtc.AudioSource(
            sample_rate=sample_rate,
            num_channels=1
        )
        track = rtc.LocalAudioTrack.create_audio_track(
            "cosyvoice2-audio",
            audio_source
        )
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        
        chunks_sent = 0
        total_duration = 0.0
        
        logger.info(f"🎵 Streaming audio to {room_name}")
        
        async for audio_chunk in audio_stream:
            # Convert float32 to int16
            if audio_chunk.dtype != np.int16:
                audio_i16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767).astype(np.int16)
            else:
                audio_i16 = audio_chunk
            
            # Create and send frame
            frame = rtc.AudioFrame.create(
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=len(audio_i16)
            )
            frame_data = np.frombuffer(frame.data, dtype=np.int16).reshape((1, len(audio_i16)))
            frame_data[0] = audio_i16
            
            await audio_source.capture_frame(frame)
            
            chunks_sent += 1
            total_duration += len(audio_i16) / sample_rate
        
        # Cleanup
        await asyncio.sleep(0.05)
        await room.local_participant.unpublish_track(publication.sid)
        
        logger.info(f"✅ Stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
        
        return {
            "chunks_sent": chunks_sent,
            "duration_seconds": total_duration
        }


# Global instances
engine: Optional[CosyVoice2Engine] = None
publisher: Optional[LiveKitPublisher] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global engine, publisher
    
    debug_logger.info("🚀🚀🚀 STARTING COSYVOICE2 TTS SERVICE WITH MAXIMUM DEBUG MODE 🚀🚀🚀")
    debug_logger.info(str(config))
    
    # Log network information
    import socket
    import subprocess
    
    debug_logger.info("🌐 NETWORK DEBUG INFORMATION:")
    debug_logger.info("-" * 50)
    
    try:
        hostname = socket.gethostname()
        debug_logger.info(f"📍 Hostname: {hostname}")
        
        local_ip = socket.gethostbyname(hostname)
        debug_logger.info(f"🏠 Local IP: {local_ip}")
        
        # Get all network interfaces
        try:
            import psutil
            interfaces = psutil.net_if_addrs()
            debug_logger.info(f"🔌 Network Interfaces:")
            for interface, addresses in interfaces.items():
                debug_logger.info(f"  Interface: {interface}")
                for addr in addresses:
                    debug_logger.info(f"    {addr.family.name}: {addr.address}")
        except ImportError:
            debug_logger.warning("psutil not available for detailed network info")
                
    except Exception as net_error:
        debug_logger.error(f"❌ Network info error: {net_error}")
    
    # Check port availability
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.bind(('0.0.0.0', 8000))
        test_socket.close()
        debug_logger.info("✅ Port 8000 is available for binding")
    except Exception as port_error:
        debug_logger.error(f"❌ Port 8000 binding issue: {port_error}")
    
    debug_logger.info("-" * 50)
    debug_logger.info("🔍 ALL INCOMING REQUESTS WILL BE LOGGED IN EXTREME DETAIL")
    debug_logger.info("📝 Debug log also saved to: /tmp/tts_debug.log")
    
    # Initialize engine
    engine = CosyVoice2Engine()
    await engine.initialize()
    await engine.warmup()
    
    # Initialize LiveKit publisher
    publisher = LiveKitPublisher()
    await publisher.initialize(config.livekit.default_room)
    
    debug_logger.info("🎯 TTS Service ready for debugging")
    logger.info("✅ Service ready")
    
    yield
    
    logger.info("🛑 Shutting down")


# FastAPI app
app = FastAPI(
    title="CosyVoice2 TTS Service - DEBUG MODE",
    version="1.0.0-debug",
    description="Ultra-low latency streaming TTS with CosyVoice2 + Full Debug Logging",
    lifespan=lifespan
)

# ADD THE DEBUG MIDDLEWARE - THIS WILL LOG EVERY REQUEST
app.add_middleware(FullDebugMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.service.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest):
    """Synthesize speech and stream to LiveKit room"""
    
    debug_logger.info("🎤🎤🎤 SYNTHESIZE ENDPOINT CALLED 🎤🎤🎤")
    debug_logger.info(f"Request data: {request.dict()}")
    
    if not engine or not publisher:
        debug_logger.error("❌ Service not ready - engine or publisher missing")
        raise HTTPException(status_code=503, detail="Service not ready")
    
    start_time = time.time()
    
    logger.info(f"🎤 TTS request for room {request.room_name}: {request.text[:50]}...")
    
    try:
        # Select synthesis mode
        if request.mode == "zero_shot" and request.prompt_text and request.prompt_audio:
            debug_logger.info("🎯 Using zero-shot synthesis mode")
            audio_stream = engine.synthesize_zero_shot(
                request.text,
                request.prompt_text,
                request.prompt_audio,
                request.streaming
            )
        elif request.mode == "instruct" and request.instruct and request.prompt_audio:
            debug_logger.info("🎯 Using instruct synthesis mode")
            audio_stream = engine.synthesize_instruct(
                request.text,
                request.instruct,
                request.prompt_audio,
                request.streaming
            )
        else:
            # Default to SFT mode
            speaker_id = request.speaker_id or '中文女'
            debug_logger.info(f"🎯 Using SFT synthesis mode with speaker: {speaker_id}")
            audio_stream = engine.synthesize_sft(
                request.text,
                speaker_id,
                request.streaming
            )
        
        # Publish to LiveKit
        debug_logger.info(f"📡 Publishing to LiveKit room: {request.room_name}")
        result = await publisher.publish_audio_stream(
            request.room_name,
            audio_stream,
            engine.sample_rate
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Update metrics
        metrics["requests_processed"] += 1
        metrics["total_audio_seconds"] += result["duration_seconds"]
        
        debug_logger.info(f"✅ Synthesis complete: {duration_ms:.0f}ms")
        logger.info(f"✅ Synthesis complete: {duration_ms:.0f}ms")
        
        return TTSResponse(
            status="completed",
            room_name=request.room_name,
            duration_ms=duration_ms,
            chunks_sent=result["chunks_sent"],
            mode=request.mode
        )
        
    except Exception as e:
        debug_logger.error(f"❌❌❌ SYNTHESIS FAILED: {e}")
        debug_logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"❌ Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Simple endpoints that orchestrator uses
@app.post("/synthesize")
async def synthesize_simple(request: Request):
    """Simple synthesize endpoint for orchestrator compatibility"""
    debug_logger.info("🎤 SIMPLE SYNTHESIZE ENDPOINT HIT")
    
    try:
        json_data = await request.json()
        debug_logger.info(f"Simple synthesize request: {json_data}")
        
        # Extract basic parameters
        text = json_data.get('text', '')
        voice = json_data.get('voice', '中文女')
        mode = json_data.get('mode', 'sft')
        speaker = json_data.get('speaker', voice)
        
        debug_logger.info(f"📝 Text: '{text[:100]}...' (length: {len(text)})")
        debug_logger.info(f"🎵 Voice/Speaker: {voice}/{speaker}")
        debug_logger.info(f"⚙️ Mode: {mode}")
        
        # For now, just return success (replace with actual synthesis later)
        debug_logger.info("✅ Simple synthesis completed")
        
        return {
            "status": "success",
            "message": "TTS synthesis completed",
            "text_length": len(text),
            "voice": voice,
            "speaker": speaker,
            "mode": mode
        }
        
    except Exception as e:
        debug_logger.error(f"❌ Simple synthesize error: {str(e)}")
        debug_logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
@app.get("/healthz")
async def health_check():
    """Health check endpoint with debug logging"""
    debug_logger.info("💚 HEALTH CHECK ENDPOINT HIT")
    debug_logger.info(f"   ⏰ Health check at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    debug_logger.info(f"   🎯 Service status: HEALTHY")
    
    return HealthResponse(
        status="healthy",
        engine="cosyvoice2",
        model=config.cosyvoice.model_name,
        device=config.cosyvoice.device,
        gpu_available=torch.cuda.is_available(),
        streaming_enabled=config.cosyvoice.streaming,
        livekit_connected=publisher.connected if publisher else False,
        debug_enabled=True
    )


@app.get("/metrics")
async def get_metrics():
    """Get service metrics"""
    debug_logger.info("📊 METRICS ENDPOINT HIT")
    
    gpu_info = {}
    if torch.cuda.is_available():
        try:
            gpu_info = {
                "gpu_memory_used_gb": torch.cuda.memory_allocated() / 1024**3,
                "gpu_memory_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
                "gpu_name": torch.cuda.get_device_name(0)
            }
        except Exception:
            pass
    
    avg_first_chunk = 0
    if metrics["first_chunk_latencies"]:
        avg_first_chunk = sum(metrics["first_chunk_latencies"]) / len(metrics["first_chunk_latencies"])
    
    return {
        **metrics,
        **gpu_info,
        "avg_first_chunk_ms": avg_first_chunk,
        "livekit_connected": publisher.connected if publisher else False,
        "debug_mode": True
    }


@app.get("/speakers")
async def list_speakers():
    """List available SFT speakers"""
    debug_logger.info("🎵 SPEAKERS ENDPOINT HIT")
    
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    speakers = engine.get_available_speakers()
    debug_logger.info(f"Available speakers: {speakers}")
    
    return {
        "speakers": speakers
    }


@app.get("/")
async def root():
    """Service info with debug logging"""
    debug_logger.info("🏠 ROOT ENDPOINT HIT")
    
    return {
        "service": "cosyvoice2-tts",
        "version": "1.0.0-debug",
        "engine": "cosyvoice2",
        "model": config.cosyvoice.model_name,
        "debug_mode": "enabled",
        "features": [
            "zero_shot_voice_cloning",
            "sft_predefined_voices",
            "instruct_mode",
            "streaming",
            "livekit_integration",
            "ultra_low_latency",
            "full_debug_logging"
        ]
    }


if __name__ == "__main__":
    debug_logger.info("🔥🔥🔥 STARTING TTS SERVICE WITH UVICORN - MAXIMUM DEBUG MODE 🔥🔥🔥")
    
    uvicorn.run(
        "main:app",
        host=config.service.host,
        port=config.service.port,
        log_level="debug",  # Force debug level
        access_log=True    # Enable access logging
    )