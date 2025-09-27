# June/services/june-orchestrator/app.py
# FIXED: Enhanced Gemini integration with proper error handling and diagnostics

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import time
import os
import json
import asyncio
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June Orchestrator", 
    version="3.0.0",
    description="June AI Platform Orchestrator with Enhanced Gemini Integration"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    text: str
    language: Optional[str] = "en"
    include_audio: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    metadata: Optional[Dict[str, Any]] = {}

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: Optional[str] = "unknown"
    debug_info: Optional[Dict[str, Any]] = None

class GeminiService:
    """Enhanced Gemini API service with better error handling"""
    
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = None
        self.available_models = []
        self.last_error = None
        self.is_initialized = False
        self.initialize()
    
    def initialize(self):
        """Initialize Gemini API with comprehensive error handling"""
        if not self.api_key:
            logger.warning("❌ GEMINI_API_KEY not set or empty")
            self.last_error = "API key not configured"
            return False
        
        if len(self.api_key) < 20:
            logger.warning(f"❌ GEMINI_API_KEY appears invalid (too short): {self.api_key[:10]}...")
            self.last_error = "API key appears invalid"
            return False
        
        try:
            import google.generativeai as genai
            
            # Configure the API
            genai.configure(api_key=self.api_key)
            logger.info(f"✅ Gemini API configured with key: {self.api_key[:10]}...{self.api_key[-4:]}")
            
            # List available models
            try:
                models_list = genai.list_models()
                self.available_models = [m.name for m in models_list if 'generateContent' in m.supported_generation_methods]
                logger.info(f"📋 Available Gemini models: {self.available_models}")
            except Exception as e:
                logger.warning(f"⚠️ Could not list models: {e}")
                # Use known models as fallback
                self.available_models = [
                    "models/gemini-pro",
                    "models/gemini-1.5-pro-latest", 
                    "models/gemini-1.5-flash",
                    "models/gemini-1.5-flash-latest"
                ]
            
            # Try to initialize with the best available model
            models_to_try = [
                "gemini-1.5-flash",      # Latest and fastest
                "gemini-1.5-pro-latest", # Most capable
                "gemini-pro",            # Stable fallback
                "gemini-1.0-pro",        # Legacy
            ]
            
            for model_name in models_to_try:
                try:
                    logger.info(f"🔧 Trying to initialize model: {model_name}")
                    self.model = genai.GenerativeModel(model_name)
                    
                    # Test the model with a simple prompt
                    test_response = self.model.generate_content("Say 'test'")
                    if test_response and test_response.text:
                        logger.info(f"✅ Successfully initialized with model: {model_name}")
                        logger.info(f"🧪 Test response: {test_response.text[:50]}")
                        self.is_initialized = True
                        return True
                        
                except Exception as e:
                    logger.warning(f"⚠️ Model {model_name} failed: {str(e)[:100]}")
                    self.last_error = str(e)
                    continue
            
            logger.error("❌ All Gemini models failed to initialize")
            return False
            
        except ImportError as e:
            logger.error(f"❌ google-generativeai not installed: {e}")
            self.last_error = "google-generativeai library not installed"
            return False
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            self.last_error = str(e)
            return False
    
    async def generate_response(
        self, 
        text: str, 
        language: str = "en",
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> tuple[str, str, Dict[str, Any]]:
        """Generate response with comprehensive error handling"""
        
        debug_info = {
            "api_key_set": bool(self.api_key),
            "api_key_prefix": self.api_key[:10] + "..." if self.api_key else "none",
            "is_initialized": self.is_initialized,
            "last_error": self.last_error,
            "available_models": self.available_models
        }
        
        if not self.is_initialized:
            logger.warning("⚠️ Gemini not initialized, attempting reinitialization...")
            self.initialize()
            
        if not self.model:
            logger.warning("⚠️ No Gemini model available, using fallback")
            return self._get_fallback_response(text, language), "fallback", debug_info
        
        try:
            # Build a proper prompt
            system_prompt = self._get_system_prompt(language)
            full_prompt = f"{system_prompt}\n\nUser: {text}\n\nAssistant:"
            
            # Configure generation settings
            generation_config = {
                "temperature": temperature,
                "top_p": 1,
                "top_k": 1,
                "max_output_tokens": max_tokens,
            }
            
            logger.info(f"🤖 Generating Gemini response for: '{text[:50]}...'")
            
            # Generate response with timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    full_prompt,
                    generation_config=generation_config
                ),
                timeout=30.0
            )
            
            if response and response.text:
                logger.info(f"✅ Gemini response generated: '{response.text[:50]}...'")
                debug_info["success"] = True
                return response.text, "gemini", debug_info
            else:
                logger.warning("⚠️ Empty response from Gemini")
                debug_info["error"] = "Empty response"
                return self._get_fallback_response(text, language), "fallback", debug_info
                
        except asyncio.TimeoutError:
            logger.error("⏱️ Gemini request timed out")
            debug_info["error"] = "Request timeout"
            return self._get_fallback_response(text, language), "fallback-timeout", debug_info
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            debug_info["error"] = str(e)
            self.last_error = str(e)
            return self._get_fallback_response(text, language), "fallback-error", debug_info
    
    def _get_system_prompt(self, language: str) -> str:
        """Get system prompt based on language"""
        prompts = {
            "en": "You are JUNE, an intelligent and helpful AI assistant. Provide clear, accurate, and helpful responses.",
            "es": "Eres JUNE, un asistente de IA inteligente y útil. Proporciona respuestas claras, precisas y útiles en español.",
            "fr": "Vous êtes JUNE, un assistant IA intelligent et utile. Fournissez des réponses claires, précises et utiles en français."
        }
        return prompts.get(language, prompts["en"])
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        """Generate intelligent fallback response"""
        text_lower = text.lower()
        
        # Language-specific responses
        responses = {
            "en": {
                "greeting": "Hello! I'm JUNE, your AI assistant. How can I help you today?",
                "help": "I'm here to assist you with any questions or tasks. What would you like help with?",
                "thanks": "You're welcome! Is there anything else I can help you with?",
                "default": f"I understand you're asking about '{text}'. While I'm currently running in limited mode, I'll do my best to help you."
            },
            "es": {
                "greeting": "¡Hola! Soy JUNE, tu asistente de IA. ¿Cómo puedo ayudarte hoy?",
                "help": "Estoy aquí para ayudarte con cualquier pregunta o tarea. ¿En qué te gustaría que te ayudara?",
                "thanks": "¡De nada! ¿Hay algo más en lo que pueda ayudarte?",
                "default": f"Entiendo que preguntas sobre '{text}'. Aunque actualmente estoy funcionando en modo limitado, haré mi mejor esfuerzo para ayudarte."
            },
            "fr": {
                "greeting": "Bonjour! Je suis JUNE, votre assistant IA. Comment puis-je vous aider aujourd'hui?",
                "help": "Je suis là pour vous aider avec toutes vos questions ou tâches. En quoi puis-je vous aider?",
                "thanks": "De rien! Y a-t-il autre chose que je puisse faire pour vous?",
                "default": f"Je comprends que vous demandez à propos de '{text}'. Bien que je fonctionne actuellement en mode limité, je ferai de mon mieux pour vous aider."
            }
        }
        
        lang_responses = responses.get(language, responses["en"])
        
        # Determine response type
        if any(word in text_lower for word in ["hello", "hi", "hey", "hola", "bonjour"]):
            return lang_responses["greeting"]
        elif any(word in text_lower for word in ["help", "assist", "ayuda", "aide"]):
            return lang_responses["help"]
        elif any(word in text_lower for word in ["thanks", "thank", "gracias", "merci"]):
            return lang_responses["thanks"]
        else:
            return lang_responses["default"]
    
    def get_status(self) -> Dict[str, Any]:
        """Get current Gemini service status"""
        return {
            "initialized": self.is_initialized,
            "api_key_configured": bool(self.api_key),
            "api_key_prefix": self.api_key[:10] + "..." if self.api_key else "not_set",
            "model_loaded": self.model is not None,
            "available_models": self.available_models,
            "last_error": self.last_error
        }

# Initialize Gemini service
gemini_service = GeminiService()

@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "June Orchestrator",
        "version": "3.0.0",
        "status": "healthy",
        "ai_status": "gemini_enhanced",
        "endpoints": {
            "health": "/healthz",
            "chat": "/v1/chat",
            "debug": "/debug/routes",
            "gemini_status": "/debug/gemini",
            "test_chat": "/debug/test-chat"
        }
    }

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "3.0.0",
        "gemini_status": gemini_service.get_status()
    }

@app.get("/debug/routes")
async def debug_routes():
    """List all available routes"""
    routes = []
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
                "name": getattr(route, 'name', 'unknown')
            })
    return {"routes": routes, "total": len(routes)}

@app.get("/debug/gemini")
async def debug_gemini():
    """Detailed Gemini service status"""
    status = gemini_service.get_status()
    
    # Try to list actual models from API
    try:
        import google.generativeai as genai
        if gemini_service.api_key:
            genai.configure(api_key=gemini_service.api_key)
            models = genai.list_models()
            status["live_models"] = [
                {
                    "name": m.name,
                    "display_name": getattr(m, 'display_name', 'N/A'),
                    "description": getattr(m, 'description', 'N/A')[:100]
                }
                for m in models
            ]
    except Exception as e:
        status["live_models_error"] = str(e)
    
    return status

@app.post("/debug/test-chat")
async def test_chat():
    """Test chat endpoint with predefined message"""
    test_messages = [
        "What is 2 + 2?",
        "Tell me a joke",
        "What's the capital of France?"
    ]
    
    import random
    test_text = random.choice(test_messages)
    
    response, provider, debug = await gemini_service.generate_response(test_text)
    
    return {
        "test_input": test_text,
        "response": response,
        "provider": provider,
        "debug_info": debug
    }

async def optional_auth(authorization: Optional[str] = Header(None)):
    """Optional authentication"""
    # For now, allow all requests
    return True

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth: bool = Depends(optional_auth)):
    """Main chat endpoint with enhanced Gemini integration"""
    start_time = time.time()
    
    try:
        logger.info(f"📨 Chat request: '{request.text[:100]}...' (lang: {request.language})")
        
        # Generate AI response
        ai_response, ai_provider, debug_info = await gemini_service.generate_response(
            request.text,
            request.language,
            request.temperature,
            request.max_tokens
        )
        
        response_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Chat response completed in {response_time}ms using {ai_provider}")
        
        # Include debug info if requested
        include_debug = request.metadata.get("include_debug", False)
        
        return ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=ai_provider,
            debug_info=debug_info if include_debug else None
        )
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}", exc_info=True)
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"I apologize, but I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error",
            debug_info={"error": str(e), "type": type(e).__name__}
        )

@app.get("/v1/version")
async def version():
    """Get version information"""
    return {
        "version": "3.0.0",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_time": os.getenv("BUILD_TIME", datetime.now().isoformat()),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "gemini_status": gemini_service.get_status()
    }

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting June Orchestrator v3.0.0")
    
    # Log environment
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'production')}")
    logger.info(f"Log Level: {os.getenv('LOG_LEVEL', 'INFO')}")
    
    # Initialize Gemini
    if gemini_service.is_initialized:
        logger.info("✅ Gemini service initialized successfully")
    else:
        logger.warning(f"⚠️ Gemini service not initialized: {gemini_service.last_error}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")