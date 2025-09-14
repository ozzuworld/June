# June/services/june-stt/app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
import logging, json
import base64
import time
import io
from typing import Optional
import tempfile
import os

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
# Service-to-Service Transcription Endpoint (ENHANCED)
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
        
        # Determine audio format from content type and file extension
        content_type = audio.content_type or ""
        filename = audio.filename or ""
        
        logger.info(f"Audio content type: {content_type}, filename: {filename}")
        
        # Try to determine the best encoding format
        encoding_format = speech.RecognitionConfig.AudioEncoding.LINEAR16  # Default
        
        if ".wav" in filename.lower() or "wav" in content_type.lower():
            encoding_format = speech.RecognitionConfig.AudioEncoding.LINEAR16
        elif ".m4a" in filename.lower() or ".aac" in filename.lower() or "mp4" in content_type.lower():
            encoding_format = speech.RecognitionConfig.AudioEncoding.MP3  # Close enough for m4a
        elif ".flac" in filename.lower() or "flac" in content_type.lower():
            encoding_format = speech.RecognitionConfig.AudioEncoding.FLAC
        elif ".opus" in filename.lower() or "opus" in content_type.lower():
            encoding_format = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
        
        # Configure recognition with detected format
        config = speech.RecognitionConfig(
            encoding=encoding_format,
            sample_rate_hertz=16000,
            language_code=language,
            enable_automatic_punctuation=True,
            use_enhanced=True,  # Use enhanced model if available
            model="latest_long",  # Best model for general use
        )
        
        logger.info(f"Using audio encoding: {encoding_format}")
        
        # If the format detection fails, try multiple formats
        audio_formats_to_try = [
            encoding_format,  # Detected format first
            speech.RecognitionConfig.AudioEncoding.LINEAR16,
            speech.RecognitionConfig.AudioEncoding.MP3,
            speech.RecognitionConfig.AudioEncoding.FLAC,
            speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        ]
        
        transcription_result = None
        confidence = 0.0
        
        for encoding_format in audio_formats_to_try:
            try:
                config.encoding = encoding_format
                audio_speech = speech.RecognitionAudio(content=audio_content)
                
                # Perform the transcription
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
        
        if not transcription_result:
            # If all formats fail, try to convert the audio using ffmpeg if available
            logger.warning("All audio formats failed, attempting conversion...")
            
            try:
                # Save audio to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".original") as temp_file:
                    temp_file.write(audio_content)
                    temp_input = temp_file.name
                
                # Convert to WAV using ffmpeg
                temp_output = temp_input + ".wav"
                
                # Try ffmpeg conversion
                import subprocess
                result = subprocess.run([
                    'ffmpeg', '-i', temp_input, 
                    '-ar', '16000', '-ac', '1', '-f', 'wav',
                    temp_output
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(temp_output):
                    # Read converted audio
                    with open(temp_output, 'rb') as f:
                        converted_audio = f.read()
                    
                    # Try transcription with converted audio
                    config.encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
                    audio_speech = speech.RecognitionAudio(content=converted_audio)
                    response = speech_client.recognize(config=config, audio=audio_speech)
                    
                    if response.results:
                        transcription_result = response.results[0].alternatives[0].transcript
                        confidence = response.results[0].alternatives[0].confidence
                        logger.info(f"✅ Transcription successful after conversion: '{transcription_result}'")
                    
                    # Cleanup
                    os.unlink(temp_output)
                
                # Cleanup
                os.unlink(temp_input)
                
            except Exception as conv_error:
                logger.error(f"Audio conversion failed: {conv_error}")
        
        if not transcription_result:
            # Final fallback
            if len(audio_content) > 1000:
                transcription_result = "I detected audio but couldn't transcribe it clearly. The audio format might not be supported."
            else:
                transcription_result = "No clear audio detected. Please try speaking louder or closer to the microphone."
            confidence = 0.1
        
        return {
            "text": transcription_result,
            "language": language,
            "confidence": confidence,
            "duration": len(audio_content) / 16000,
            "processed_by": "june-stt",
            "caller": calling_service,
            "audio_size_bytes": len(audio_content)
        }
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Transcription failed: {str(e)}"}
        )

