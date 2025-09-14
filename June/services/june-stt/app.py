# June/services/june-stt/app.py - ENHANCED VERSION
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
import logging, json
import base64
import time
import io
from typing import Optional
import tempfile
import os
import subprocess

from authz import verify_token_query
from shared.auth_service import require_service_auth

# Add Google Cloud Speech client
try:
    from google.cloud import speech
    speech_client = speech.SpeechClient()
    logger = logging.getLogger("uvicorn.error")
    logger.info("✅ Google Cloud Speech client initialized")
except Exception as e:
    logger = logging.getLogger("uvicorn.error")
    logger.warning(f"⚠️ Failed to initialize Speech client: {e}")
    speech_client = None

app = FastAPI(title="June STT Service", version="1.0.0")

# -----------------------------------------------------------------------------
# Enhanced Service-to-Service Transcription Endpoint
# -----------------------------------------------------------------------------
@app.post("/v1/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("en-US"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    Enhanced transcription endpoint with better audio format handling
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"Transcription request from service: {calling_service}")
    
    try:
        # Read audio file
        audio_content = await audio.read()
        logger.info(f"Received audio: {len(audio_content)} bytes, format: {audio.content_type}, language: {language}")
        
        if not speech_client:
            # Enhanced fallback when Google Cloud Speech is not available
            if len(audio_content) > 1000:  # Non-empty audio
                mock_text = "This is a mock transcription. Please configure Google Cloud Speech for real transcription."
            else:
                mock_text = "No audio detected or audio too short."
                
            return {
                "text": mock_text,
                "language": language,
                "confidence": 0.95,
                "duration": len(audio_content) / 16000,
                "processed_by": "june-stt (mock)",
                "caller": calling_service
            }
        
        # ENHANCED: Better audio format detection and conversion
        content_type = audio.content_type or ""
        filename = audio.filename or ""
        
        logger.info(f"Audio details - Content Type: {content_type}, Filename: {filename}, Size: {len(audio_content)} bytes")
        
        # Create temporary files for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".original") as temp_input:
            temp_input.write(audio_content)
            temp_input_path = temp_input.name
        
        try:
            # ENHANCED: Try multiple approaches for audio processing
            transcription_result = None
            confidence = 0.0
            
            # Approach 1: Try direct transcription with multiple formats
            for encoding_format in [
                speech.RecognitionConfig.AudioEncoding.MP3,  # Try MP3 first (good for m4a)
                speech.RecognitionConfig.AudioEncoding.LINEAR16,
                speech.RecognitionConfig.AudioEncoding.FLAC,
                speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            ]:
                try:
                    config = speech.RecognitionConfig(
                        encoding=encoding_format,
                        sample_rate_hertz=16000,  # Match the mobile app setting
                        language_code=language,
                        enable_automatic_punctuation=True,
                        use_enhanced=True,
                        model="latest_long",
                    )
                    
                    audio_speech = speech.RecognitionAudio(content=audio_content)
                    
                    logger.info(f"Trying transcription with encoding: {encoding_format}")
                    response = speech_client.recognize(config=config, audio=audio_speech)
                    
                    if response.results:
                        transcription_result = response.results[0].alternatives[0].transcript
                        confidence = response.results[0].alternatives[0].confidence
                        logger.info(f"✅ Transcription successful with {encoding_format}: '{transcription_result}' (confidence: {confidence})")
                        break
                    else:
                        logger.warning(f"No results with {encoding_format}")
                        
                except Exception as format_error:
                    logger.warning(f"Failed with {encoding_format}: {format_error}")
                    continue
            
            # Approach 2: If direct transcription fails, convert using ffmpeg
            if not transcription_result:
                logger.warning("Direct transcription failed, attempting audio conversion...")
                
                # Convert to WAV using ffmpeg
                temp_output_path = temp_input_path + ".wav"
                
                try:
                    # Enhanced ffmpeg command for better audio conversion
                    ffmpeg_cmd = [
                        'ffmpeg', '-i', temp_input_path,
                        '-ar', '16000',  # Match sample rate
                        '-ac', '1',      # Mono
                        '-f', 'wav',     # WAV format
                        '-acodec', 'pcm_s16le',  # 16-bit PCM
                        '-y',            # Overwrite output
                        temp_output_path
                    ]
                    
                    result = subprocess.run(
                        ffmpeg_cmd, 
                        capture_output=True, 
                        text=True, 
                        timeout=30
                    )
                    
                    if result.returncode == 0 and os.path.exists(temp_output_path):
                        logger.info("✅ Audio conversion successful")
                        
                        # Read converted audio
                        with open(temp_output_path, 'rb') as f:
                            converted_audio = f.read()
                        
                        # Try transcription with converted audio
                        config = speech.RecognitionConfig(
                            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                            sample_rate_hertz=16000,
                            language_code=language,
                            enable_automatic_punctuation=True,
                            use_enhanced=True,
                            model="latest_long",
                        )
                        
                        audio_speech = speech.RecognitionAudio(content=converted_audio)
                        response = speech_client.recognize(config=config, audio=audio_speech)
                        
                        if response.results:
                            transcription_result = response.results[0].alternatives[0].transcript
                            confidence = response.results[0].alternatives[0].confidence
                            logger.info(f"✅ Transcription successful after conversion: '{transcription_result}'")
                        
                        # Cleanup converted file
                        os.unlink(temp_output_path)
                    else:
                        logger.error(f"ffmpeg conversion failed: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    logger.error("Audio conversion timed out")
                except Exception as conv_error:
                    logger.error(f"Audio conversion failed: {conv_error}")
            
            # Approach 3: Final fallback with better messaging
            if not transcription_result:
                logger.warning(f"All transcription attempts failed for audio from {calling_service}")
                
                if len(audio_content) > 1000:
                    transcription_result = "I detected audio but couldn't transcribe it clearly. Please try speaking more clearly or check your microphone."
                else:
                    transcription_result = "The audio seems too short or empty. Please try recording a longer message."
                confidence = 0.1
            
            return {
                "text": transcription_result,
                "language": language,
                "confidence": confidence,
                "duration": len(audio_content) / 16000,
                "processed_by": "june-stt",
                "caller": calling_service,
                "audio_size_bytes": len(audio_content),
                "original_format": content_type,
                "filename": filename
            }
            
        finally:
            # Cleanup temporary files
            try:
                os.unlink(temp_input_path)
            except:
                pass
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Transcription failed: {str(e)}"}
        )

# Keep your existing health endpoints
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-stt", 
        "timestamp": time.time(),
        "status": "healthy",
        "speech_client_available": speech_client is not None,
        "ffmpeg_available": subprocess.run(['which', 'ffmpeg'], capture_output=True).returncode == 0
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "june-stt", "status": "running"}