# June/services/june-orchestrator/app.py
# Enhanced orchestrator with external TTS integration

import os
import time
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Gemini imports
USING_NEW_SDK = False
try:
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
    logger.info("✅ Using new Google GenAI SDK")
except ImportError:
    try:
        import google.generativeai as genai
        USING_NEW_SDK = False
        logger.info("✅ Using legacy google-generativeai library")
    except ImportError:
        logger.error("❌ No Gemini library found")
        genai = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from tts_client import get_tts_client

app = FastAPI(title="June Orchestrator", version="3.1.0", description="June AI Platform Orchestrator with TTS integration")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class AudioConfig(BaseModel):
    voice: Optional[str] = Field(default="default")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    language: Optional[str] = Field(default="EN")
    reference_audio_b64: Optional[str] = Field(default=None)

class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1000, ge=1, le=4000)
    include_audio: Optional[bool] = Field(default=False)
    audio_config: Optional[AudioConfig] = Field(default=None)

class AudioData(BaseModel):
    data: str = Field(...)
    content_type: str = Field(default="audio/wav")
    size_bytes: int = Field(...)
    voice: str = Field(...)
    speed: float = Field(...)
    language: str = Field(...)

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"
    audio: Optional[AudioData] = Field(default=None)

class GeminiService:
    def __init__(self):
        self.model = None
        self.client = None
        self.api_key = None
        self.is_available = False
        self.initialize()
    
    def initialize(self):
        try:
            self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
            
            if not self.api_key or len(self.api_key) < 30:
                logger.warning("❌ GEMINI_API_KEY not set or invalid")
                return False
            
            if not genai:
                logger.warning("❌ No Gemini library available")
                return False
            
            if USING_NEW_SDK:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ New GenAI SDK configured")
                
                try:
                    response = self.client.models.generate_content(model='gemini-1.5-flash', contents='Say "Hello"')
                    if response and response.text:
                        self.is_available = True
                        return True
                except Exception:
                    try:
                        response = self.client.models.generate_content(model='gemini-2.0-flash-exp', contents='Say "Hello"')
                        if response and response.text:
                            self.is_available = True
                            return True
                    except Exception as e:
                        logger.warning(f"❌ New SDK test failed: {e}")
                        return False
            else:
                genai.configure(api_key=self.api_key)
                try:
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    test_response = self.model.generate_content("Say 'Hello'")
                    if test_response and test_response.text:
                        self.is_available = True
                        return True
                except Exception as e:
                    logger.error(f"❌ Legacy SDK test failed: {e}")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            return False
    
    async def generate_response(self, text: str, language: str = "en", temperature: float = 0.7) -> tuple[str, str]:
        if not self.is_available:
            return self._get_fallback_response(text, language), "fallback"
        
        try:
            system_prompts = {
                "en": "You are JUNE, a helpful AI assistant. Provide clear, accurate, and helpful responses.",
                "es": "Eres JUNE, un asistente de IA útil. Proporciona respuestas claras, precisas y útiles en español.",
                "fr": "Vous êtes JUNE, un assistant IA utile. Fournissez des réponses claires, précises et utiles en français."
            }
            
            system_prompt = system_prompts.get(language, system_prompts["en"])
            full_prompt = f"{system_prompt}\n\nUser: {text}\n\nAssistant:"
            
            if USING_NEW_SDK and self.client:
                try:
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=1000)
                    )
                except Exception:
                    response = self.client.models.generate_content(
                        model='gemini-2.0-flash-exp',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=1000)
                    )
                
                if response and response.text:
                    return response.text.strip(), "gemini-new-sdk"
            else:
                if self.model:
                    generation_config = genai.types.GenerationConfig(temperature=temperature, max_output_tokens=1000)
                    response = self.model.generate_content(full_prompt, generation_config=generation_config)
                    
                    if response and response.text:
                        return response.text.strip(), "gemini-legacy"
            
            return self._get_fallback_response(text, language), "fallback"
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return self._get_fallback_response(text, language), "fallback"
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        responses = {
            "en": {"greeting": "Hello! I'm JUNE, your AI assistant. How can I help you today?", "default": f"I understand you're asking about '{text}'. I'm here to help you."},
            "es": {"greeting": "¡Hola! Soy JUNE, tu asistente de IA. ¿Cómo puedo ayudarte hoy?", "default": f"Entiendo que preguntas sobre '{text}'. Estoy aquí para ayudarte."},
            "fr": {"greeting": "Bonjour! Je suis JUNE, votre assistant IA. Comment puis-je vous aider aujourd'hui?", "default": f"Je comprends que vous demandez à propos de '{text}'. Je suis là pour vous aider."}
        }
        
        lang_responses = responses.get(language, responses["en"])
        text_lower = text.lower()
        if any(word in text_lower for word in ["hello", "hi", "hey", "hola", "bonjour"]):
            return lang_responses["greeting"]
        return lang_responses["default"]

gemini_service = GeminiService()

@app.get("/")
async def root():
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    
    return {
        "service": "June Orchestrator",
        "version": "3.1.0",
        "status": "healthy",
        "features": {"ai_chat": gemini_service.is_available, "text_to_speech": tts_status.get("available", False)},
        "tts_service_url": os.getenv("TTS_SERVICE_URL", "not_configured"),
        "endpoints": {"health": "/healthz", "chat": "/v1/chat", "tts_status": "/v1/tts/status"}
    }

@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "june-orchestrator", "version": "3.1.0", "timestamp": time.time()}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start_time = time.time()
    
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        ai_response, provider = await gemini_service.generate_response(request.text.strip(), request.language, request.temperature)
        
        response_time = int((time.time() - start_time) * 1000)
        
        chat_response = ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=provider
        )
        
        if request.include_audio:
            try:
                tts_client = get_tts_client()
                audio_config = request.audio_config or AudioConfig()
                
                audio_result = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice=audio_config.voice,
                    speed=audio_config.speed,
                    language=audio_config.language,
                    reference_audio_b64=audio_config.reference_audio_b64
                )
                
                audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                
                chat_response.audio = AudioData(
                    data=audio_b64,
                    content_type=audio_result["content_type"],
                    size_bytes=audio_result["size_bytes"],
                    voice=audio_result["voice"],
                    speed=audio_result["speed"],
                    language=audio_result["language"]
                )
                
            except Exception as e:
                logger.error(f"❌ TTS generation failed: {e}")
        
        return chat_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"I apologize, but I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

@app.get("/v1/tts/status")
async def tts_status():
    tts_client = get_tts_client()
    return await tts_client.get_status()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v3.1.0 with external TTS integration")
    logger.info(f"TTS Service URL: {os.getenv('TTS_SERVICE_URL', 'not_configured')}")
    
    if gemini_service.is_available:
        logger.info("✅ Gemini service ready")
    else:
        logger.warning("⚠️ Gemini service not ready")
    
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    if tts_status.get("available", False):
        logger.info("✅ External TTS service ready")
    else:
        logger.warning("⚠️ External TTS service not reachable")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
