# June/services/june-orchestrator/app.py
# Clean, working orchestrator with proper Gemini integration

import os
import time
import logging
from datetime import datetime
from typing import Optional

# Try to import Gemini libraries (new SDK first, then legacy)
try:
    # New Google GenAI SDK (recommended)
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
    logger.info("✅ Using new Google GenAI SDK")
except ImportError:
    try:
        # Legacy Google Generative AI library
        import google.generativeai as genai
        USING_NEW_SDK = False
        logger.info("✅ Using legacy google-generativeai library")
    except ImportError:
        logger.error("❌ No Gemini library found. Install either:")
        logger.error("   pip install google-genai  # (new SDK)")
        logger.error("   pip install google-generativeai  # (legacy)")
        raise ImportError("Gemini library not found")
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="June Orchestrator",
    version="3.0.0",
    description="Clean June AI Platform Orchestrator with Gemini integration"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# MODELS
# ============================================================================

class ChatRequest(BaseModel):
    text: str
    language: Optional[str] = "en"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000

class ChatResponse(BaseModel):
    ok: bool
    message: dict
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"

# ============================================================================
# GEMINI SERVICE
# ============================================================================

class GeminiService:
    def __init__(self):
        self.model = None
        self.client = None
        self.api_key = None
        self.initialize()
    
    def initialize(self):
        """Initialize Gemini with proper error handling for both SDKs"""
        try:
            # Get API key from environment
            self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
            
            if not self.api_key:
                logger.error("❌ GEMINI_API_KEY not set")
                return False
            
            if len(self.api_key) < 30:  # Basic validation
                logger.error("❌ GEMINI_API_KEY appears invalid")
                return False
            
            if USING_NEW_SDK:
                # New Google GenAI SDK
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ New GenAI SDK configured with key: {self.api_key[:10]}...")
                
                # Test with a simple generation
                try:
                    response = self.client.models.generate_content(
                        model='gemini-2.0-flash-exp',
                        contents='Say "Hello"'
                    )
                    if response and response.text:
                        logger.info(f"✅ New SDK test successful: {response.text}")
                        return True
                except Exception as e:
                    logger.warning(f"gemini-2.0-flash-exp failed: {e}, trying gemini-1.5-flash...")
                    try:
                        response = self.client.models.generate_content(
                            model='gemini-1.5-flash',
                            contents='Say "Hello"'
                        )
                        if response and response.text:
                            logger.info(f"✅ New SDK test successful: {response.text}")
                            return True
                    except Exception as e:
                        logger.error(f"❌ New SDK test failed: {e}")
                        return False
            else:
                # Legacy Google Generative AI library
                genai.configure(api_key=self.api_key)
                logger.info(f"✅ Legacy GenAI configured with key: {self.api_key[:10]}...")
                
                # Initialize model (use the most reliable model)
                try:
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    logger.info("✅ Using gemini-1.5-flash model")
                except Exception as e:
                    logger.warning(f"Failed to load gemini-1.5-flash: {e}")
                    try:
                        self.model = genai.GenerativeModel('gemini-pro')
                        logger.info("✅ Using gemini-pro model")
                    except Exception as e:
                        logger.error(f"Failed to load any Gemini model: {e}")
                        return False
                
                # Test the model with a simple prompt
                try:
                    test_response = self.model.generate_content("Say 'Hello'")
                    if test_response and test_response.text:
                        logger.info(f"✅ Legacy SDK test successful: {test_response.text}")
                        return True
                except Exception as e:
                    logger.error(f"❌ Legacy SDK test failed: {e}")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            return False
    
    async def generate_response(self, text: str, language: str = "en", temperature: float = 0.7) -> tuple[str, str]:
        """Generate response using either new or legacy Gemini SDK"""
        
        if USING_NEW_SDK and not self.client:
            logger.warning("⚠️ New Gemini SDK not available, using fallback")
            return self._get_fallback_response(text, language), "fallback"
        elif not USING_NEW_SDK and not self.model:
            logger.warning("⚠️ Legacy Gemini not available, using fallback")
            return self._get_fallback_response(text, language), "fallback"
        
        try:
            # Create system prompt based on language
            system_prompts = {
                "en": "You are JUNE, a helpful AI assistant. Provide clear, accurate, and helpful responses.",
                "es": "Eres JUNE, un asistente de IA útil. Proporciona respuestas claras, precisas y útiles en español.",
                "fr": "Vous êtes JUNE, un assistant IA utile. Fournissez des réponses claires, précises et utiles en français."
            }
            
            system_prompt = system_prompts.get(language, system_prompts["en"])
            full_prompt = f"{system_prompt}\n\nUser: {text}\n\nAssistant:"
            
            logger.info(f"🤖 Generating response for: '{text[:50]}...'")
            
            if USING_NEW_SDK:
                # New Google GenAI SDK
                try:
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            temperature=temperature,
                            max_output_tokens=1000,
                        )
                    )
                except Exception as e:
                    logger.warning(f"gemini-1.5-flash failed: {e}, trying gemini-2.0-flash-exp...")
                    response = self.client.models.generate_content(
                        model='gemini-2.0-flash-exp',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            temperature=temperature,
                            max_output_tokens=1000,
                        )
                    )
                
                if response and response.text:
                    logger.info(f"✅ Generated response: '{response.text[:50]}...'")
                    return response.text.strip(), "gemini-new-sdk"
                else:
                    logger.warning("⚠️ Empty response from new Gemini SDK")
                    return self._get_fallback_response(text, language), "fallback"
            else:
                # Legacy Google Generative AI library
                generation_config = genai.types.GenerationConfig(
                    temperature=temperature,
                    top_p=1,
                    top_k=1,
                    max_output_tokens=1000,
                )
                
                response = self.model.generate_content(
                    full_prompt,
                    generation_config=generation_config
                )
                
                if response and response.text:
                    logger.info(f"✅ Generated response: '{response.text[:50]}...'")
                    return response.text.strip(), "gemini-legacy"
                else:
                    logger.warning("⚠️ Empty response from legacy Gemini")
                    return self._get_fallback_response(text, language), "fallback"
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return self._get_fallback_response(text, language), "fallback"
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        """Generate fallback response when Gemini is unavailable"""
        responses = {
            "en": {
                "greeting": "Hello! I'm JUNE, your AI assistant. How can I help you today?",
                "default": f"I understand you're asking about '{text}'. I'm currently running in limited mode, but I'm here to help you."
            },
            "es": {
                "greeting": "¡Hola! Soy JUNE, tu asistente de IA. ¿Cómo puedo ayudarte hoy?",
                "default": f"Entiendo que preguntas sobre '{text}'. Estoy funcionando en modo limitado, pero estoy aquí para ayudarte."
            },
            "fr": {
                "greeting": "Bonjour! Je suis JUNE, votre assistant IA. Comment puis-je vous aider aujourd'hui?",
                "default": f"Je comprends que vous demandez à propos de '{text}'. Je fonctionne en mode limité, mais je suis là pour vous aider."
            }
        }
        
        lang_responses = responses.get(language, responses["en"])
        
        # Simple response logic
        text_lower = text.lower()
        if any(word in text_lower for word in ["hello", "hi", "hey", "hola", "bonjour"]):
            return lang_responses["greeting"]
        else:
            return lang_responses["default"]
    
    def get_status(self) -> dict:
        """Get current Gemini service status"""
        if USING_NEW_SDK:
            return {
                "sdk_type": "new_google_genai_sdk",
                "api_key_configured": bool(self.api_key),
                "client_ready": self.client is not None,
                "ready": bool(self.api_key and self.client)
            }
        else:
            return {
                "sdk_type": "legacy_google_generativeai",
                "api_key_configured": bool(self.api_key),
                "model_loaded": self.model is not None,
                "ready": bool(self.api_key and self.model)
            }

# Initialize Gemini service
gemini_service = GeminiService()

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "June Orchestrator",
        "version": "3.0.0",
        "status": "healthy",
        "gemini_status": gemini_service.get_status(),
        "endpoints": {
            "health": "/healthz",
            "chat": "/v1/chat",
            "version": "/v1/version",
            "debug": "/debug/status"
        }
    }

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "3.0.0",
        "timestamp": time.time(),
        "gemini_ready": gemini_service.get_status()["ready"]
    }

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint with Gemini integration"""
    start_time = time.time()
    
    try:
        logger.info(f"📨 Chat request: '{request.text[:100]}...' (lang: {request.language})")
        
        # Input validation
        if not request.text or not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        if len(request.text) > 10000:  # Reasonable limit
            raise HTTPException(status_code=400, detail="Text too long (max 10000 characters)")
        
        # Generate AI response
        ai_response, provider = await gemini_service.generate_response(
            request.text.strip(),
            request.language,
            request.temperature
        )
        
        response_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Chat response completed in {response_time}ms using {provider}")
        
        return ChatResponse(
            ok=True,
            message={
                "text": ai_response,
                "role": "assistant"
            },
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=provider
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={
                "text": f"I apologize, but I encountered an error: {str(e)}",
                "role": "error"
            },
            response_time_ms=response_time,
            ai_provider="error"
        )

@app.get("/v1/version")
async def version():
    """Get version information"""
    return {
        "version": "3.0.0",
        "service": "june-orchestrator",
        "build_time": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "gemini_status": gemini_service.get_status()
    }

@app.get("/debug/status")
async def debug_status():
    """Debug endpoint for service status"""
    gemini_status = gemini_service.get_status()
    
    return {
        "service": "june-orchestrator",
        "version": "3.0.0",
        "environment": {
            "GEMINI_API_KEY": "set" if os.getenv("GEMINI_API_KEY") else "not_set",
            "ENVIRONMENT": os.getenv("ENVIRONMENT", "not_set")
        },
        "gemini": gemini_status,
        "timestamp": time.time()
    }

@app.post("/debug/test-chat")
async def test_chat():
    """Test chat endpoint with predefined message"""
    test_messages = [
        "Hello, how are you?",
        "What's 2 + 2?",
        "Tell me about artificial intelligence",
        "What can you help me with?"
    ]
    
    import random
    test_text = random.choice(test_messages)
    
    # Use the same chat endpoint
    request = ChatRequest(text=test_text)
    return await chat(request)

# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting June Orchestrator v3.0.0")
    
    # Log configuration
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'production')}")
    logger.info(f"Gemini API Key: {'✅ Set' if os.getenv('GEMINI_API_KEY') else '❌ Not Set'}")
    
    # Initialize Gemini
    if gemini_service.get_status()["ready"]:
        logger.info("✅ Gemini service ready")
    else:
        logger.warning("⚠️ Gemini service not ready - will use fallback responses")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")