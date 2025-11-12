"""
ASR Streaming Microservice based on whisper_streaming
FastAPI server with WebSocket support for real-time transcription.
Also starts a LiveKit subscriber worker on startup.
"""

import asyncio
import io
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import soundfile
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    # Provided by ufal/whisper_streaming (copied into /app by Dockerfile)
    from whisper_online import FasterWhisperASR, OnlineASRProcessor, VACOnlineASRProcessor
except ImportError:  # raised at runtime if missing
    FasterWhisperASR = None  # type: ignore
    OnlineASRProcessor = None  # type: ignore
    VACOnlineASRProcessor = None  # type: ignore

from livekit_worker import run_livekit_worker

# Logging ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Constants -------------------------------------------------------------------

SAMPLING_RATE = 16000
CHANNELS = 1

# FastAPI app -----------------------------------------------------------------

app = FastAPI(
    title="ASR Streaming Microservice",
    description="Real-time speech-to-text transcription using Whisper Streaming",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Config / Service ------------------------------------------------------------

class ASRConfig(BaseModel):
    model: str = "large-v2"
    language: str = "en"
    task: str = "transcribe"  # or "translate"
    use_vac: bool = True
    min_chunk_size: float = 1.0
    buffer_trimming: str = "segment"


class ASRService:
    """Wraps FasterWhisperASR + streaming processors."""

    def __init__(self, config: ASRConfig):
        self.config = config
        self.asr = None
        self.is_ready = False

    async def initialize(self) -> None:
        """Load Whisper model and warm it up."""
        if FasterWhisperASR is None:
            raise RuntimeError("whisper_online is not installed inside the container")

        logger.info(
            "Loading Whisper %s model for %s...",
            self.config.model,
            self.config.language,
        )

        self.asr = FasterWhisperASR(
            lan=self.config.language,
            modelsize=self.config.model,
            cache_dir=None,
            model_dir=None,
        )

        if self.config.task == "translate":
            self.asr.set_translate_task()

        if self.config.use_vac:
            self.asr.use_vad()

        logger.info("Model loaded successfully")

        # Warmup
        try:
            logger.info("Warming up ASR model...")
            dummy_audio = np.zeros(SAMPLING_RATE, dtype=np.float32)

            if self.config.use_vac:
                # FIXED: Correct parameter order
                # VACOnlineASRProcessor(online_chunk_size, asr, tokenizer, logfile, buffer_trimming)
                processor = VACOnlineASRProcessor(
                    self.config.min_chunk_size,  # online_chunk_size - matches min_chunk_size
                    self.asr,                     # asr model
                    None,                         # tokenizer (None for segment trimming)
                    logfile=None,
                    buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size),
                )
            else:
                processor = OnlineASRProcessor(
                    self.asr,
                    None,  # tokenizer
                    logfile=None,
                    buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size),
                )

            processor.insert_audio_chunk(dummy_audio)
            list(processor.process_iter())
            processor.finish()
            logger.info("ASR model warmed up successfully")
        except Exception as e:
            logger.warning("Warmup failed (non-critical): %s", e)

        self.is_ready = True

    def create_processor(self):
        """Create a new streaming processor instance."""
        if not self.is_ready or self.asr is None:
            raise RuntimeError("ASR service not initialized yet")

        if self.config.use_vac:
            # FIXED: Correct parameter order
            # VACOnlineASRProcessor(online_chunk_size, asr, tokenizer, logfile, buffer_trimming)
            return VACOnlineASRProcessor(
                self.config.min_chunk_size,  # online_chunk_size - NOT vac_chunk_size!
                self.asr,                     # asr model
                None,                         # tokenizer (None for segment trimming)
                logfile=None,
                buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size),
            )
        else:
            return OnlineASRProcessor(
                self.asr,
                None,  # tokenizer
                logfile=None,
                buffer_trimming=(self.config.buffer_trimming, self.config.min_chunk_size),
            )


# Single global service used by both WebSocket and LiveKit worker
asr_service: Optional[ASRService] = None


# Startup / health ------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """Initialize ASR service and start LiveKit worker."""
    global asr_service

    config = ASRConfig(
        model="base",
        language="en",
        task="transcribe",
        use_vac=True,
        min_chunk_size=1.0,
    )

    asr_service = ASRService(config)
    await asr_service.initialize()
    logger.info("ASR Microservice started successfully")

    # Start LiveKit worker in the background
    asyncio.create_task(run_livekit_worker(asr_service))
    logger.info("LiveKit worker started")


@app.get("/")
async def root():
    return {
        "service": "ASR Streaming Microservice",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    if asr_service is None or not asr_service.is_ready:
        return JSONResponse(
            status_code=503,
            content={"status": "initializing"},
        )
    return {"status": "ok"}


@app.get("/config")
async def get_config():
    if asr_service is None:
        raise HTTPException(status_code=503, detail="ASR service not initialized")
    return {
        "model": asr_service.config.model,
        "language": asr_service.config.language,
        "task": asr_service.config.task,
        "use_vac": asr_service.config.use_vac,
        "min_chunk_size": asr_service.config.min_chunk_size,
        "sampling_rate": SAMPLING_RATE,
    }


# WebSocket endpoint ----------------------------------------------------------

@app.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    """
    Real-time transcription over WebSocket.

    Expects raw PCM 16-bit LE audio at 16 kHz, mono.
    """
    await websocket.accept()

    if asr_service is None or not asr_service.is_ready:
        await websocket.send_json(
            {"type": "error", "message": "ASR service not initialized"}
        )
        await websocket.close(code=1011)
        return

    processor = asr_service.create_processor()
    session_id = id(processor)
    logger.info("WebSocket session %s started", session_id)

    try:
        while True:
            try:
                data = await websocket.receive_bytes()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected for session %s", session_id)
                break

            if not data:
                continue

            try:
                audio_buffer = io.BytesIO(data)
                sf = soundfile.SoundFile(
                    audio_buffer,
                    channels=CHANNELS,
                    endian="LITTLE",
                    samplerate=SAMPLING_RATE,
                    subtype="PCM_16",
                    format="RAW",
                )
                audio = sf.read(dtype=np.float32)

                processor.insert_audio_chunk(audio)

                for output in processor.process_iter():
                    if output[0] is not None:
                        beg, end, text = output
                        result = {
                            "type": "partial",
                            "text": text,
                            "start": float(beg),
                            "end": float(end),
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                        await websocket.send_json(result)
            except Exception as e:
                logger.error("Error processing audio chunk: %s", e)
                await websocket.send_json({"type": "error", "message": str(e)})
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            output = processor.finish()
            if output[0] is not None:
                beg, end, text = output
                await websocket.send_json(
                    {
                        "type": "final",
                        "text": text,
                        "start": float(beg),
                        "end": float(end),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
        except Exception:
            pass

        logger.info("Session %s closed", session_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")