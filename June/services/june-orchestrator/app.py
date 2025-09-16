# June/services/june-orchestrator/app.py - CHATTERBOX TTS ONLY
import os
import json
import uuid
import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, Depends

# Import the shared auth module
from shared.auth_service import create_service_auth_client, require_service_auth, ServiceAuthClient

# Import Firebase auth (keeping existing functionality)
from authz import get_current_user

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="June Orchestrator", version="1.0.0")
voice_router = APIRouter()

logger = logging.getLogger("orchestrator.voice")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
FIREBASE_PROJECT_ID    = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_WEB_API_KEY   = os.getenv("FIREBASE_WEB_API_KEY", "")
INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_SHARED_SECRET", "")

# AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Initialize AI if available
ai_model = None
try:
    if GEMINI_API_KEY:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        
        genai.configure(api_key=GEMINI_API_KEY)
        
        # Create AI model with safety settings
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 1024,
        }
        
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }
        
        ai_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            safety_settings=safety_settings,
        )
        
        logger.info("✅ Gemini AI model initialized")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not set - using fallback responses")
except ImportError:
    logger.warning("⚠️ google-generativeai not installed - using fallback responses")
except Exception as e:
    logger.error(f"⚠️ Failed to initialize AI model: {e}")

# Service URLs - ONLY CHATTERBOX TTS
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")  # Points ONLY to Chatterbox TTS

# Audio defaults
DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en-US")

# -----------------------------------------------------------------------------
# AI Helper Functions
# -----------------------------------------------------------------------------
async def generate_ai_response(user_input: str, user_context: dict = None) -> str:
    """Generate AI response using Gemini"""
    if not ai_model:
        return f"I received your message: '{user_input}'. However, AI is currently not configured. This is a placeholder response."
    
    try:
        # Create a conversational prompt
        system_prompt = """You are June, a helpful AI assistant. You are knowledgeable, friendly, and concise. 
        You can help with various tasks, answer questions, and have engaging conversations.
        
        Key traits:
        - Be helpful and informative
        - Keep responses conversational and engaging
        - If you don't know something, say so honestly
        - Be concise but thorough when needed
        """
        
        # Combine system prompt with user input
        full_prompt = f"{system_prompt}\n\nUser: {user_input}\n\nJune:"
        
        # Generate response
        response = ai_model.generate_content(full_prompt)
        
        if response.text:
            return response.text.strip()
        else:
            return "I'm having trouble generating a response right now. Could you try rephrasing your question?"
            
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        return f"I'm experiencing some technical difficulties. Here's what I can tell you about '{user_input}': I'd be happy to help, but I'm having trouble processing that right now."

# -----------------------------------------------------------------------------
# Service authentication setup
# -----------------------------------------------------------------------------
try:
    service_auth = create_service_auth_client("orchestrator")
    logger.info("✅ Service authentication initialized")
except Exception as e:
    logger.warning(f"⚠️ Service authentication not available: {e}")
    service_auth = None

# -----------------------------------------------------------------------------
# Chatterbox TTS client with authentication
# -----------------------------------------------------------------------------

# Initialize TTS client with proper Chatterbox support
class ChatterboxTTSClient:
    def __init__(self, base_url: str, auth_client: ServiceAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth = auth_client
        self.available_voices = {}
        self.initialized = False
        
    async def initialize(self):
        """Initialize and get available voices from TTS service"""
        try:
            response = await self.auth.make_authenticated_request(
                "GET",
                f"{self.base_url}/v1/voices",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                self.available_voices = data.get("voices", {})
                self.initialized = True
                logger.info(f"✅ Chatterbox TTS initialized with voices: {list(self.available_voices.keys())}")
            else:
                logger.error(f"Failed to get voices: {response.status_code}")
                self.available_voices = {
                    "af_bella": "Default female voice",
                    "am_adam": "Default male voice"
                }
                
        except Exception as e:
            logger.error(f"⚠️ Failed to initialize Chatterbox TTS: {e}")
            # Set default voices as fallback
            self.available_voices = {
                "af_bella": "Default female voice",
                "am_adam": "Default male voice"
            }
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "af_bella",
        speed: float = 1.0,
        temperature: float = 0.3,
        exaggeration: float = 0.5,
        audio_encoding: str = "MP3"
    ) -> bytes:
        """Call Chatterbox TTS service"""
        if not self.auth:
            raise Exception("Service authentication not configured")
        
        # Validate and fallback for voice
        if voice not in self.available_voices and voice != "default":
            logger.warning(f"Voice '{voice}' not available, using af_bella")
            voice = "af_bella"
        
        try:
            # Build query parameters
            params = {
                "text": text,
                "voice": voice,
                "speed": speed,
                "temperature": temperature,
                "exaggeration": exaggeration,
                "audio_encoding": audio_encoding
            }
            
            logger.info(f"🎵 Calling TTS with voice={voice}, temp={temperature}, exag={exaggeration}")
            
            response = await self.auth.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/tts",
                params=params,
                timeout=30.0
            )
            
            response.raise_for_status()
            
            audio_content = response.content
            logger.info(f"✅ Chatterbox TTS synthesis successful: {len(audio_content)} bytes")
            
            return audio_content
            
        except Exception as e:
            logger.error(f"❌ Chatterbox TTS synthesis failed: {e}")
            raise


# In process-audio endpoint, ensure proper audio handling:
@app.post("/v1/process-audio")
async def process_audio(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Process audio through STT -> AI -> TTS pipeline"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"🎤 Audio processing request from service: {calling_service}")
    
    audio_data = payload.get("audio_data")  # base64 encoded audio
    if not audio_data:
        return {
            "error": "No audio data provided",
            "transcription": "",
            "response_text": "Please provide audio data",
            "response_audio": None
        }
    
    try:
        # Step 1: Decode the base64 audio
        import base64
        audio_bytes = base64.b64decode(audio_data)
        logger.info(f"📊 Received audio: {len(audio_bytes)} bytes")
        
        # Step 2: Call STT service for transcription
        transcription_text = ""
        stt_confidence = 0.0
        
        if stt_client:
            try:
                # Save audio to temporary file for multipart upload
                import tempfile
                import os
                
                with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as temp_file:
                    temp_file.write(audio_bytes)
                    temp_file.flush()
                    temp_path = temp_file.name
                
                logger.info(f"📁 Saved temp audio file: {temp_path}")
                
                # Call STT service with multipart form
                with open(temp_path, "rb") as audio_file:
                    response = await stt_client.auth.make_authenticated_request(
                        "POST",
                        f"{STT_SERVICE_URL}/v1/transcribe",
                        files={"audio": ("audio.m4a", audio_file, "audio/mp4")},
                        data={"language": "en-US"},
                        timeout=30.0
                    )
                
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass
                
                if response.status_code == 200:
                    stt_result = response.json()
                    transcription_text = stt_result.get("text", "")
                    stt_confidence = stt_result.get("confidence", 0.0)
                    logger.info(f"✅ STT transcription: '{transcription_text}' (confidence: {stt_confidence})")
                else:
                    logger.error(f"❌ STT failed with status {response.status_code}: {response.text}")
                    transcription_text = "Could not transcribe audio"
                    
            except Exception as stt_error:
                logger.error(f"❌ STT service call failed: {stt_error}")
                transcription_text = "Speech recognition failed"
        else:
            logger.warning("⚠️ STT client not available")
            transcription_text = "Speech recognition service unavailable"
        
        # If transcription failed or is empty, provide fallback
        if not transcription_text or transcription_text in ["Could not transcribe audio", "Speech recognition failed"]:
            transcription_text = "Hello, how can I help you?"
            logger.warning(f"⚠️ Using fallback transcription: '{transcription_text}'")
        
        # Step 3: Process through AI for response generation
        reply = ""
        ai_model_used = "fallback"
        
        try:
            # Add context about the interaction
            user_context = {
                "caller": calling_service,
                "interaction_type": "voice",
                "confidence": stt_confidence
            }
            
            # Generate AI response
            reply = await generate_ai_response(transcription_text, user_context)
            ai_model_used = "gemini-1.5-flash" if ai_model else "fallback"
            
            logger.info(f"🤖 AI response generated: '{reply[:100]}...' using {ai_model_used}")
            
        except Exception as ai_error:
            logger.error(f"❌ AI generation failed: {ai_error}")
            # Fallback response
            reply = f"I heard you say: '{transcription_text}'. How can I assist you with that?"
        
        # Ensure we have a reply
        if not reply:
            reply = "I'm here to help. Could you please repeat your question?"
        
        # Step 4: Generate TTS audio from the AI response
        audio_b64 = None
        tts_metadata = {}
        
        if tts_client and reply:
            try:
                logger.info(f"🎵 Generating speech for: '{reply[:50]}...'")
                
                # Analyze text for emotion/tone
                temperature = 0.3
                exaggeration = 0.5
                voice = "af_bella"  # Default voice
                
                # Simple emotion detection
                text_lower = reply.lower()
                if any(word in text_lower for word in ["excited", "amazing", "wonderful", "fantastic", "great"]):
                    temperature = 0.7
                    exaggeration = 0.8
                    logger.info("😊 Detected positive emotion")
                elif any(word in text_lower for word in ["sorry", "unfortunately", "apologize", "sad"]):
                    temperature = 0.2
                    exaggeration = 0.3
                    logger.info("😔 Detected apologetic/sad tone")
                elif any(word in text_lower for word in ["urgent", "important", "critical", "warning"]):
                    temperature = 0.5
                    exaggeration = 0.7
                    voice = "af_nicole"  # More serious voice
                    logger.info("⚠️ Detected urgent tone")
                elif "?" in reply:
                    temperature = 0.4
                    exaggeration = 0.6
                    logger.info("❓ Detected question")
                
                # Call TTS service with parameters
                tts_params = {
                    "text": reply,
                    "voice": voice,
                    "speed": 1.0,
                    "temperature": temperature,
                    "exaggeration": exaggeration,
                    "audio_encoding": "MP3"
                }
                
                response = await tts_client.auth.make_authenticated_request(
                    "POST",
                    f"{TTS_SERVICE_URL}/v1/tts",
                    params=tts_params,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    audio_response = response.content
                    if audio_response and len(audio_response) > 0:
                        # Encode audio to base64 for response
                        audio_b64 = base64.b64encode(audio_response).decode('utf-8')
                        logger.info(f"✅ TTS audio generated: {len(audio_response)} bytes")
                        
                        # Extract metadata from response headers
                        tts_metadata = {
                            "voice": response.headers.get("X-Voice", voice),
                            "engine": response.headers.get("X-TTS-Engine", "chatterbox"),
                            "processing_time": response.headers.get("X-Processing-Time", "unknown")
                        }
                    else:
                        logger.error("❌ TTS returned empty audio")
                else:
                    logger.error(f"❌ TTS failed with status {response.status_code}: {response.text}")
                    
            except Exception as tts_error:
                logger.error(f"❌ TTS service call failed: {tts_error}")
        else:
            logger.warning("⚠️ TTS client not available or no reply to synthesize")
        
        # Step 5: Prepare complete response
        response_data = {
            "transcription": transcription_text,
            "transcription_confidence": stt_confidence,
            "response_text": reply,
            "response_audio": audio_b64,
            "processed_by": "orchestrator",
            "caller": calling_service,
            "ai_model": ai_model_used,
            "tts_engine": "chatterbox" if audio_b64 else None,
            "tts_metadata": tts_metadata if audio_b64 else {},
            "processing_complete": True,
            "has_audio": audio_b64 is not None
        }
        
        # Log summary
        logger.info(f"""
        ✅ Audio processing complete:
        - Transcription: '{transcription_text[:50]}...'
        - AI Response: '{reply[:50]}...'
        - Audio Generated: {audio_b64 is not None}
        - Caller: {calling_service}
        """)
        
        return response_data
        
    except Exception as e:
        logger.error(f"❌ Audio processing failed: {e}", exc_info=True)
        
        # Return error response with helpful information
        return {
            "error": str(e),
            "transcription": "Error processing audio",
            "response_text": "I apologize, but I encountered an error processing your audio. Please try again or use text input instead.",
            "response_audio": None,
            "processed_by": "orchestrator",
            "caller": calling_service,
            "processing_complete": False,
            "has_audio": False
        }
# -----------------------------------------------------------------------------
# Health and config endpoints
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    """Health check endpoint for load balancers"""
    return {
        "ok": True, 
        "service": "june-orchestrator", 
        "timestamp": time.time(),
        "status": "healthy",
        "ai_enabled": ai_model is not None,
        "tts_engine": "chatterbox"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator", 
        "status": "running",
        "version": "1.0.0",
        "ai_enabled": ai_model is not None,
        "tts_engine": "chatterbox"
    }

@app.get("/configz")
async def configz():
    """Configuration endpoint for debugging"""
    return {
        "FIREBASE_PROJECT_ID": FIREBASE_PROJECT_ID,
        "STT_SERVICE_URL": STT_SERVICE_URL,
        "TTS_SERVICE_URL": TTS_SERVICE_URL,
        "DEFAULT_LOCALE": DEFAULT_LOCALE,
        "service_auth_enabled": service_auth is not None,
        "stt_client_ready": stt_client is not None,
        "tts_client_ready": tts_client is not None,
        "ai_model_enabled": ai_model is not None,
        "gemini_api_key_present": bool(GEMINI_API_KEY),
        "tts_engine": "chatterbox",
        "available_voices": getattr(tts_client, 'available_voices', {}) if tts_client else {}
    }

# -----------------------------------------------------------------------------
# Protected service endpoints with Chatterbox TTS
# -----------------------------------------------------------------------------
@app.post("/v1/chat")
async def chat(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Chat endpoint protected by service authentication with AI integration"""
    user_text = (payload or {}).get("user_input", "")
    calling_service = service_auth_data.get("client_id", "unknown")
    
    logger.info(f"Chat request from service: {calling_service}")
    
    if not user_text.strip():
        return {
            "reply": "I didn't receive any message. What would you like to talk about?",
            "processed_by": "orchestrator",
            "caller": calling_service
        }
    
    # Generate AI response
    try:
        reply = await generate_ai_response(user_text, {"caller": calling_service})
        
        return {
            "reply": reply,
            "processed_by": "orchestrator", 
            "caller": calling_service,
            "ai_model": "gemini-1.5-flash" if ai_model else "fallback",
            "tts_engine": "chatterbox"
        }
        
    except Exception as e:
        logger.error(f"Chat processing error: {e}")
        return {
            "reply": f"I apologize, but I'm having trouble processing your message right now. Error: {str(e)}",
            "processed_by": "orchestrator",
            "caller": calling_service,
            "error": str(e)
        }

@app.post("/v1/process-audio")
async def process_audio(
    payload: dict,
    service_auth_data: dict = Depends(require_service_auth)
):
    """Process audio through STT -> LLM -> TTS pipeline"""
    calling_service = service_auth_data.get("client_id", "unknown")
    logger.info(f"🎤 Audio processing request from service: {calling_service}")
    
    audio_data = payload.get("audio_data")  # base64 encoded audio
    if not audio_data:
        return {"error": "No audio data provided"}
    
    try:
        # Decode audio
        import base64
        audio_bytes = base64.b64decode(audio_data)
        logger.info(f"📊 Received audio: {len(audio_bytes)} bytes")
        
        # Step 1: Call STT service
        transcription_text = "Could not transcribe audio"
        if stt_client:
            try:
                # Save audio to temporary file for multipart upload
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as temp_file:
                    temp_file.write(audio_bytes)
                    temp_file.flush()
                    temp_path = temp_file.name
                
                # Call STT with proper multipart form
                with open(temp_path, "rb") as audio_file:
                    response = await stt_client.auth.make_authenticated_request(
                        "POST",
                        f"{STT_SERVICE_URL}/v1/transcribe",
                        files={"audio": ("audio.m4a", audio_file, "audio/mp4")},
                        data={"language": "en-US"},
                        timeout=30.0
                    )
                
                # Clean up temp file
                os.unlink(temp_path)
                
                if response.status_code == 200:
                    stt_result = response.json()
                    transcription_text = stt_result.get("text", "Could not transcribe audio")
                    logger.info(f"✅ STT transcription: '{transcription_text}'")
                else:
                    logger.error(f"❌ STT failed with status {response.status_code}")
                    
            except Exception as stt_error:
                logger.error(f"❌ STT service call failed: {stt_error}")
        
        # Step 2: Process through AI
        reply = await generate_ai_response(transcription_text, {"caller": calling_service})
        logger.info(f"🤖 AI response: '{reply[:100]}...'")
        
        # Step 3: Generate TTS audio
        audio_b64 = None
        if tts_client and reply:
            try:
                logger.info(f"🎵 Generating speech for: '{reply[:50]}...'")
                
                # Call TTS service
                audio_response = await tts_client.synthesize_speech(
                    text=reply,
                    voice="default",
                    speed=1.0,
                    audio_encoding="MP3"
                )
                
                if audio_response:
                    # Encode audio to base64 for response
                    audio_b64 = base64.b64encode(audio_response).decode('utf-8')
                    logger.info(f"✅ TTS audio generated: {len(audio_response)} bytes")
                else:
                    logger.error("❌ TTS returned empty audio")
                    
            except Exception as tts_error:
                logger.error(f"❌ TTS service call failed: {tts_error}")
        
        # Return complete response
        return {
            "transcription": transcription_text,
            "response_text": reply,
            "response_audio": audio_b64,  # Base64 encoded MP3
            "processed_by": "orchestrator",
            "caller": calling_service,
            "tts_available": audio_b64 is not None
        }
        
    except Exception as e:
        logger.error(f"❌ Audio processing failed: {e}")
        return {
            "error": str(e),
            "transcription": "Error processing audio",
            "response_text": "I apologize, but I encountered an error processing your audio.",
            "response_audio": None
        }

# -----------------------------------------------------------------------------
# Startup event
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize all service clients on startup"""
    global stt_client, tts_client
    
    if service_auth:
        logger.info("🔧 Initializing service clients...")
        
        try:
            # Test service authentication
            token = await service_auth.get_access_token()
            logger.info("✅ Service authentication working")
        except Exception as e:
            logger.error(f"❌ Service authentication failed: {e}")
        
        # Initialize STT client
        if STT_SERVICE_URL:
            stt_client = AuthenticatedSTTClient(STT_SERVICE_URL, service_auth)
            logger.info(f"✅ STT client configured: {STT_SERVICE_URL}")
        else:
            logger.warning("⚠️ STT_SERVICE_URL not set")
        
        # Initialize TTS client
        if TTS_SERVICE_URL:
            tts_client = ChatterboxTTSClient(TTS_SERVICE_URL, service_auth)
            logger.info(f"✅ TTS client configured: {TTS_SERVICE_URL}")
            
            # Initialize TTS to get available voices
            try:
                await tts_client.initialize()
                logger.info(f"🎤 Available TTS voices: {list(tts_client.available_voices.keys())}")
            except Exception as e:
                logger.error(f"Failed to initialize TTS: {e}")
        else:
            logger.warning("⚠️ TTS_SERVICE_URL not set")
    else:
        logger.warning("⚠️ Service authentication not available")
    
    # Test AI model
    if ai_model:
        logger.info("✅ Gemini AI model configured and ready")
    else:
        logger.warning("⚠️ AI model not available - using fallback responses")
    
    logger.info(f"""
    🚀 Orchestrator started:
    - STT: {stt_client is not None}
    - TTS: {tts_client is not None}
    - AI: {ai_model is not None}
    - Auth: {service_auth is not None}
    """)