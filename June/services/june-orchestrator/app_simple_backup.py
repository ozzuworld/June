from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import time
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June Orchestrator", 
    version="2.1.1",
    description="June AI Platform Orchestrator - Fixed Gemini API"
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
    metadata: Optional[Dict[str, Any]] = {}

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: Optional[str] = "fallback"

@app.get("/")
async def root():
    return {
        "service": "June Orchestrator",
        "version": "2.1.1",
        "status": "healthy",
        "ai_status": "gemini_fixed",
        "endpoints": {
            "health": "/healthz",
            "chat": "/v1/chat",
            "debug": "/debug/routes"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "2.1.1",
        "gemini_api": "configured"
    }

@app.get("/debug/routes")
async def debug_routes():
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
    """Debug endpoint to check Gemini API status"""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    
    return {
        "has_api_key": bool(gemini_key and len(gemini_key) > 10),
        "key_prefix": gemini_key[:10] + "..." if gemini_key else "not_set",
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "recommended_models": [
            "gemini-pro",
            "gemini-1.5-pro", 
            "gemini-1.5-flash"
        ]
    }

async def optional_auth(authorization: Optional[str] = Header(None)):
    return True

def get_gemini_response(text: str, language: str = "en") -> tuple[str, str]:
    """Get response from Gemini AI with proper error handling"""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    
    if not gemini_key or len(gemini_key) < 10:
        logger.info("🤖 No valid Gemini API key - using fallback responses")
        return get_fallback_response(text, language), "fallback"
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        
        # Try different model names in order of preference
        models_to_try = [
            "gemini-pro",           # Most stable
            "gemini-1.5-pro",       # Latest pro
            "gemini-1.5-flash",     # Latest flash
            "gemini-pro-latest"     # Fallback
        ]
        
        for model_name in models_to_try:
            try:
                logger.info(f"🤖 Trying Gemini model: {model_name}")
                model = genai.GenerativeModel(model_name)
                
                prompt = f"""You are OZZU, a helpful AI assistant for the June platform.
                
User message: {text}
Language: {language}

Respond helpfully and naturally in {language}. Keep responses concise but informative."""
                
                response = model.generate_content(prompt)
                ai_response = response.text
                
                logger.info(f"✅ Gemini AI success with model: {model_name}")
                return ai_response, f"gemini-{model_name}"
                
            except Exception as model_error:
                logger.warning(f"⚠️ Model {model_name} failed: {str(model_error)[:100]}")
                continue
        
        # If all models failed
        logger.warning("⚠️ All Gemini models failed - using fallback")
        return get_fallback_response(text, language), "fallback"
        
    except ImportError:
        logger.warning("⚠️ google-generativeai library not available")
        return get_fallback_response(text, language), "fallback"
    except Exception as e:
        logger.warning(f"⚠️ Gemini API error: {str(e)[:100]}")
        return get_fallback_response(text, language), "fallback"

def get_fallback_response(text: str, language: str = "en") -> str:
    """Generate intelligent fallback responses"""
    
    # Smart fallback responses based on input
    text_lower = text.lower()
    
    if language == "es":
        if any(word in text_lower for word in ["hola", "hello", "hi"]):
            return f"¡Hola! Soy OZZU, tu asistente de IA. Dijiste: '{text}'. ¿Cómo puedo ayudarte hoy?"
        elif any(word in text_lower for word in ["gracias", "thanks"]):
            return "¡De nada! Estoy aquí para ayudarte. ¿Hay algo más en lo que pueda asistirte?"
        elif "?" in text:
            return f"Entiendo tu pregunta: '{text}'. Aunque estoy funcionando en modo básico, haré mi mejor esfuerzo para ayudarte."
        else:
            return f"Entiendo que dijiste: '{text}'. Soy OZZU y estoy aquí para ayudarte en todo lo que pueda."
    
    elif language == "fr":
        if any(word in text_lower for word in ["bonjour", "hello", "salut"]):
            return f"Bonjour! Je suis OZZU, votre assistant IA. Vous avez dit: '{text}'. Comment puis-je vous aider?"
        elif any(word in text_lower for word in ["merci", "thanks"]):
            return "De rien! Je suis là pour vous aider. Y a-t-il autre chose que je puisse faire pour vous?"
        elif "?" in text:
            return f"Je comprends votre question: '{text}'. Bien que je fonctionne en mode de base, je ferai de mon mieux pour vous aider."
        else:
            return f"Je comprends que vous avez dit: '{text}'. Je suis OZZU et je suis là pour vous aider."
    
    else:  # English
        if any(word in text_lower for word in ["hello", "hi", "hey"]):
            return f"Hello! I'm OZZU, your AI assistant. You said: '{text}'. How can I help you today?"
        elif any(word in text_lower for word in ["thanks", "thank you"]):
            return "You're welcome! I'm here to help. Is there anything else I can assist you with?"
        elif "?" in text:
            return f"I understand your question: '{text}'. While I'm running in basic mode, I'll do my best to help you."
        elif any(word in text_lower for word in ["help", "assist"]):
            return f"I'd be happy to help! You said: '{text}'. I'm OZZU, your AI assistant, and I'm here to assist you with whatever you need."
        else:
            return f"I understand you said: '{text}'. I'm OZZU, your AI assistant, and I'm here to help you however I can!"

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth: bool = Depends(optional_auth)):
    """Main chat endpoint with fixed Gemini API"""
    start_time = time.time()
    
    try:
        logger.info(f"📨 Chat request: '{request.text[:100]}...'")
        
        # Get AI response
        ai_response, ai_provider = get_gemini_response(request.text, request.language)
        
        response_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Chat response completed in {response_time}ms using {ai_provider}")
        
        return ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=ai_provider
        )
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"Sorry, I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

@app.get("/v1/version")
async def version():
    return {
        "version": "2.1.1",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_time": os.getenv("BUILD_TIME", "unknown"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "gemini_fixed": True
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
