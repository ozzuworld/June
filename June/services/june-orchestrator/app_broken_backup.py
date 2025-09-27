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
    version="2.2.0",
    description="June AI Platform with REAL Gemini AI Integration"
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
        "version": "2.2.0",
        "status": "healthy",
        "ai_status": "gemini_integrated",
        "endpoints": {
            "health": "/healthz",
            "chat": "/v1/chat",
            "debug": "/debug/routes",
            "gemini_debug": "/debug/gemini"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "2.2.0",
        "gemini_api": "integrated"
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
    
    debug_info = {
        "has_api_key": bool(gemini_key and len(gemini_key) > 10),
        "key_prefix": gemini_key[:15] + "..." if gemini_key else "not_set",
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "available_models": [],
        "library_status": "unknown"
    }
    
    # Test if google-generativeai is available
    try:
        import google.generativeai as genai
        debug_info["library_status"] = "available"
        
        if gemini_key:
            genai.configure(api_key=gemini_key)
            try:
                # Try to list models to verify API access
                models = list(genai.list_models())
                debug_info["available_models"] = [m.name for m in models[:5]]  # First 5
                debug_info["api_accessible"] = True
            except Exception as e:
                debug_info["api_accessible"] = False
                debug_info["api_error"] = str(e)[:100]
        else:
            debug_info["api_accessible"] = False
            debug_info["api_error"] = "No API key provided"
            
    except ImportError:
        debug_info["library_status"] = "not_installed"
        debug_info["library_error"] = "google-generativeai not installed"
    
    return debug_info

async def optional_auth(authorization: Optional[str] = Header(None)):
    return True

def get_gemini_response(text: str, language: str = "en") -> tuple[str, str]:
    """Get response from Gemini AI with proper error handling"""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    
    if not gemini_key or len(gemini_key) < 10:
        logger.warning("🤖 No valid Gemini API key - using fallback responses")
        return get_fallback_response(text, language), "fallback"
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        
        # Try different model names in order of preference
        models_to_try = [
            "gemini-1.5-flash",     # Latest and fastest
            "gemini-1.5-pro",       # Latest pro
            "gemini-pro",           # Stable fallback
        ]
        
        for model_name in models_to_try:
            try:
                logger.info(f"🤖 Trying Gemini model: {model_name}")
                model = genai.GenerativeModel(model_name)
                
                prompt = f"""You are OZZU, a helpful AI assistant for the June platform.

User message: {text}
Language: {language}

Respond helpfully and naturally in {language}. Be concise but informative. Do not mention that you are running in any special mode."""
                
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
        logger.error("⚠️ google-generativeai library not installed")
        return get_fallback_response(text, language), "fallback"
    except Exception as e:
        logger.error(f"⚠️ Gemini API error: {str(e)[:100]}")
        return get_fallback_response(text, language), "fallback"

def get_fallback_response(text: str, language: str = "en") -> str:
    """Generate intelligent fallback responses"""
    text_lower = text.lower()
    
    if language == "es":
        if "hola" in text_lower or "hello" in text_lower:
            return f"¡Hola! Soy OZZU. Dijiste: '{text}'. ¿Cómo puedo ayudarte? (Nota: Gemini AI no está disponible)"
        elif "2+2" in text or "suma" in text_lower:
            return "2 + 2 = 4. (Respuesta de respaldo - Gemini AI no disponible)"
        return f"Entiendo: '{text}'. Soy OZZU en modo respaldo."
    
    else:  # English
        if "hello" in text_lower or "hi" in text_lower:
            return f"Hello! I'm OZZU. You said: '{text}'. How can I help? (Note: Gemini AI unavailable)"
        elif "2+2" in text or "math" in text_lower:
            return "2 + 2 = 4. (Fallback response - Gemini AI unavailable)"
        elif "?" in text:
            return f"I understand your question: '{text}'. I'm currently in fallback mode as Gemini AI is unavailable."
        else:
            return f"I understand: '{text}'. I'm OZZU running in fallback mode."

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth: bool = Depends(optional_auth)):
    """Main chat endpoint with REAL Gemini AI integration"""
    start_time = time.time()
    
    try:
        logger.info(f"📨 Chat request: '{request.text[:100]}...'")
        
        # Get AI response (this will take 1-3 seconds if Gemini works)
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
        "version": "2.2.0",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_time": os.getenv("BUILD_TIME", "unknown"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "gemini_integrated": True
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
