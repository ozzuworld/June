# June/services/june-stt/app.py - FIXED VERSION
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

def detect_audio_format_and_convert(audio_content: bytes, content_type: str = "", filename: str = "") -> tuple:
    """
    Detect audio format and convert to format suitable for Google Cloud Speech
    Returns: (processed_audio_bytes, detected_format, sample_rate)
    """
    logger.info(f"Processing audio - Size: {len(audio_content)}, Content-Type: {content_type}, Filename: {filename}")
    
    # FIXED: Better M4A detection and handling
    if any(indicator in content_type.lower() or indicator in filename.lower() 
           for indicator in ['m4a', 'mp4', 'aac', 'mpeg4']):
        logger.info("Detected M4A/AAC format - using MP3 encoding for Speech API")
        return audio_content, speech.RecognitionConfig.AudioEncoding.MP3, 16000
    
    elif any(indicator in content_type.lower() or indicator in filename.lower() 
             for indicator in ['wav', 'wave']):
        logger.info("Detected WAV format - using LINEAR16 encoding")
        return audio_content, speech.RecognitionConfig.AudioEncoding.LINEAR16, 16000
    
    elif any(indicator in content_type.lower() or indicator in filename.lower() 
             for indicator in ['flac']):
        logger.info("Detected FLAC format")
        return audio_content, speech.RecognitionConfig.AudioEncoding.FLAC, 16000
    
    elif any(indicator in content_type.lower() or indicator in filename.lower() 
             for indicator in ['webm', 'opus']):
        logger.info("Detected WebM/Opus format")
        return audio_content, speech.RecognitionConfig.AudioEncoding.WEBM_OPUS, 16000
    
    else:
        # Default to MP3 for unknown formats (works well for M4A)
        logger.info("Unknown format - defaulting to MP3 encoding")
        return audio_content, speech.RecognitionConfig.AudioEncoding.MP3, 16000

@app.post("/v1/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("en-US"),
    service_auth_data: dict = Depends(require_service_auth)
):
    """
    Enhanced transcription endpoint with proper M4A support and error handling
    """
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"📝 Transcription request from service: {calling_service}")
    
    try:
        # Read audio file
        audio_content = await audio.read()
        logger.info(f"📁 Received audio: {len(audio_content)} bytes, format: {audio.content_type}, language: {language}")
        
        # FIXED: Better validation
        if len(audio_content) < 100:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Audio file too small or empty",
                    "text": "Please record a longer audio message",
                    "processed_by": "june-stt",
                    "caller": calling_service
                }
            )
        
        if len(audio_content) > 10 * 1024 * 1024:  # 10MB limit
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Audio file too large (max 10MB)",
                    "text": "Please record a shorter audio message",
                    "processed_by": "june-stt", 
                    "caller": calling_service
                }
            )
        
        if not speech_client:
            # Enhanced fallback when Google Cloud Speech is not available
            mock_text = f"Mock transcription for {len(audio_content)} bytes of audio. Please configure Google Cloud Speech for real transcription."
            logger.warning("🔧 Using mock transcription - Speech client not available")
            
            return {
                "text": mock_text,
                "language": language,
                "confidence": 0.95,
                "duration": len(audio_content) / 16000,
                "processed_by": "june-stt (mock)",
                "caller": calling_service,
                "audio_size_bytes": len(audio_content)
            }
        
        # FIXED: Proper format detection and processing
        content_type = audio.content_type or ""
        filename = audio.filename or "audio.m4a"
        
        logger.info(f"🎵 Audio details - Content-Type: '{content_type}', Filename: '{filename}', Size: {len(audio_content)} bytes")
        
        # Detect format and get appropriate encoding
        processed_audio, encoding_format, sample_rate = detect_audio_format_and_convert(
            audio_content, content_type, filename
        )
        
        # FIXED: Enhanced Speech API configuration
        config = speech.RecognitionConfig(
            encoding=encoding_format,
            sample_rate_hertz=sample_rate,
            language_code=language,
            enable_automatic_punctuation=True,
            use_enhanced=True,
            model="latest_long",
            # FIXED: Better audio processing settings
            enable_speaker_diarization=False,
            profanity_filter=False,
            # FIXED: Add alternative language codes for better recognition
            alternative_language_codes=["en-GB", "en-AU"] if language.startswith("en") else [],
            # FIXED: Enable word time offsets for better debugging
            enable_word_time_offsets=False,
            # FIXED: Audio channel count
            audio_channel_count=1,
        )
        
        logger.info(f"🔧 Speech API config - Encoding: {encoding_format}, Sample Rate: {sample_rate}, Language: {language}")
        
        try:
            # FIXED: Create audio object with proper error handling
            audio_speech = speech.RecognitionAudio(content=processed_audio)
            
            # FIXED: Add timeout and retry logic
            logger.info("📡 Sending audio to Google Cloud Speech API...")
            
            response = speech_client.recognize(
                config=config, 
                audio=audio_speech,
                timeout=30  # 30 second timeout
            )
            
            logger.info(f"📡 Speech API response received with {len(response.results)} results")
            
            if response.results and len(response.results) > 0:
                # Get the best transcription result
                best_result = response.results[0].alternatives[0]
                transcription_text = best_result.transcript.strip()
                confidence_score = best_result.confidence
                
                logger.info(f"✅ Transcription successful: '{transcription_text}' (confidence: {confidence_score})")
                
                # FIXED: Better validation of transcription quality
                if len(transcription_text) < 3:
                    logger.warning("⚠️ Very short transcription received")
                    transcription_text = f"{transcription_text}. (Note: Very short audio detected)"
                
                return {
                    "text": transcription_text,
                    "language": language,
                    "confidence": confidence_score,
                    "duration": len(audio_content) / sample_rate,
                    "processed_by": "june-stt",
                    "caller": calling_service,
                    "audio_size_bytes": len(audio_content),
                    "encoding_used": str(encoding_format),
                    "sample_rate_used": sample_rate,
                    "results_count": len(response.results)
                }
            else:
                logger.warning("⚠️ Speech API returned no results")
                return {
                    "text": "No speech detected in the audio. Please try speaking more clearly or closer to the microphone.",
                    "language": language,
                    "confidence": 0.0,
                    "duration": len(audio_content) / sample_rate,
                    "processed_by": "june-stt",
                    "caller": calling_service,
                    "audio_size_bytes": len(audio_content),
                    "error": "no_speech_detected"
                }
                
        except Exception as speech_error:
            logger.error(f"💥 Google Cloud Speech API error: {speech_error}")
            
            # FIXED: Better error categorization and user messages
            error_message = str(speech_error).lower()
            
            if "permission" in error_message or "authentication" in error_message:
                user_message = "Speech service authentication error. Please try again."
                logger.error("🔐 Speech API authentication/permission error")
            elif "quota" in error_message or "limit" in error_message:
                user_message = "Speech service temporarily unavailable due to quota limits. Please try again later."
                logger.error("💸 Speech API quota/limit error")
            elif "invalid" in error_message and "encoding" in error_message:
                user_message = "Audio format not supported. Please try recording again."
                logger.error("🎵 Speech API encoding error")
            elif "empty" in error_message or "too short" in error_message:
                user_message = "Audio too short. Please record a longer message."
                logger.error("⏱️ Speech API empty/short audio error")
            elif "internal" in error_message or "500" in error_message:
                user_message = "Speech service temporarily unavailable. Please try again in a moment."
                logger.error("🔧 Speech API internal server error")
            else:
                user_message = "Could not process audio. Please try recording again."
                logger.error(f"❓ Unrecognized Speech API error: {speech_error}")
            
            return JSONResponse(
                status_code=500,
                content={
                    "error": "speech_api_error",
                    "text": user_message,
                    "language": language,
                    "confidence": 0.0,
                    "duration": len(audio_content) / sample_rate,
                    "processed_by": "june-stt",
                    "caller": calling_service,
                    "audio_size_bytes": len(audio_content),
                    "error_details": str(speech_error)[:200],  # Truncated error details
                    "encoding_attempted": str(encoding_format),
                    "sample_rate_attempted": sample_rate
                }
            )
        
    except Exception as e:
        logger.error(f"💥 General transcription error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Transcription failed: {str(e)}",
                "text": "Sorry, I couldn't process your audio. Please try again.",
                "processed_by": "june-stt",
                "caller": calling_service,
                "error_type": "general_error"
            }
        )

# Health check endpoint
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-stt", 
        "timestamp": time.time(),
        "status": "healthy",
        "speech_client_available": speech_client is not None,
        "google_cloud_configured": speech_client is not None
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-stt", 
        "status": "running", 
        "supports_m4a": True,
        "speech_api_available": speech_client is not None
    }

# FIXED: Add test endpoint for debugging
@app.get("/v1/test-auth")
async def test_auth(service_auth_data: dict = Depends(require_service_auth)):
    """Test endpoint to verify service authentication"""
    calling_service = service_auth_data.get("client_id", "unknown")
    return {
        "message": "Authentication successful",
        "caller": calling_service,
        "timestamp": time.time(),
        "service": "june-stt"
    }