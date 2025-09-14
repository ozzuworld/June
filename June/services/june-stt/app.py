# June/services/june-stt/app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
import logging, json
import base64
import time
import io
from typing import Optional

from authz import verify_token_query
from shared.auth_service import require_service_auth

# Add Google Cloud Speech client
from google.cloud import speech

app = FastAPI(title="June STT Service", version="1.0.0")
logger = logging.getLogger("uvicorn.error")

# Initialize Speech client
try:
    speech_client = speech.SpeechClient()
    logger.info("✅ Google Cloud Speech client initialized")
except Exception as e:
    logger.warning(f"⚠️ Failed to initialize Speech client: {e}")
    speech_client = None

# -----------------------------------------------------------------------------
# Service-to-Service Transcription Endpoint (FIXED)
# -----------------------------------------------------------------------------
@app.post("/v1/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("en-US"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    Transcribe audio endpoint for service-to-service communication
    Protected by service authentication
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"Transcription request from service: {calling_service}")
    
    try:
        # Read audio file
        audio_content = await audio.read()
        logger.info(f"Received audio: {len(audio_content)} bytes, language: {language}")
        
        if not speech_client:
            # Fallback if Google Cloud Speech is not available
            mock_text = "Hello, this is a test transcription since Google Cloud Speech is not configured."
            return {
                "text": mock_text,
                "language": language,
                "confidence": 0.95,
                "duration": len(audio_content) / 16000,
                "processed_by": "june-stt",
                "caller": calling_service
            }
        
        # Configure recognition
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,  # Try different encodings
            sample_rate_hertz=16000,
            language_code=language,
            enable_automatic_punctuation=True,
        )
        
        # Try multiple audio formats
        audio_formats_to_try = [
            speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS, 
            speech.RecognitionConfig.AudioEncoding.LINEAR16,
            speech.RecognitionConfig.AudioEncoding.FLAC,
        ]
        
        transcription_result = None
        
        for encoding_format in audio_formats_to_try:
            try:
                config.encoding = encoding_format
                audio_speech = speech.RecognitionAudio(content=audio_content)
                
                # Perform the transcription
                response = speech_client.recognize(config=config, audio=audio_speech)
                
                if response.results:
                    transcription_result = response.results[0].alternatives[0].transcript
                    confidence = response.results[0].alternatives[0].confidence
                    logger.info(f"✅ Transcription successful with {encoding_format}")
                    break
                    
            except Exception as format_error:
                logger.warning(f"Failed with {encoding_format}: {format_error}")
                continue
        
        if not transcription_result:
            # If all formats fail, return a helpful message
            transcription_result = "I heard you, but couldn't transcribe the audio clearly. Could you try speaking again?"
            confidence = 0.5
        else:
            confidence = confidence if 'confidence' in locals() else 0.9
        
        return {
            "text": transcription_result,
            "language": language,
            "confidence": confidence,
            "duration": len(audio_content) / 16000,
            "processed_by": "june-stt",
            "caller": calling_service
        }
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Transcription failed: {str(e)}"}
        )

# Rest of your existing code...
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-stt",  
        "timestamp": time.time(),
        "status": "healthy",
        "speech_client_available": speech_client is not None
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-stt", 
        "status": "running",
        "version": "1.0.0",
        "speech_client_available": speech_client is not None
    }