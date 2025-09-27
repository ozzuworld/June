from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import time
import os
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="June Orchestrator",
    version="2.3.0",
    description="June AI Platform with REAL Gemini AI Integration - FIXED"
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
        "version": "2.3.0",
        "status": "healthy", 
        "ai_status": "REAL_GEMINI_INTEGRATED",
        "endpoints": {
            "health": "/healthz",
            "chat": "/v1/chat",
            "debug": "/debug/routes",
            "gemini_debug": "/debug/gemini",
            "test_ai": "/test/ai"
        }
    }

@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "2.3.0",
        "gemini_api": "REAL_INTEGRATION"
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
    """Debug endpoint to test Gemini API connection"""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    
    debug_info = {
        "has_api_key": bool(gemini_key and len(gemini_key) > 20),
        "key_prefix": gemini_key[:15] + "..." if gemini_key else "NOT_SET",
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "library_status": "checking...",
        "api_test": "pending"
    }
    
    # Test the Google GenAI library
    try:
        from google import genai
        debug_info["library_status"] = "google-genai available"
        
        if gemini_key:
            try:
                # Test actual API call
                client = genai.Client(api_key=gemini_key)
                test_response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents="Say 'API test successful' in exactly those words."
                )
                debug_info["api_test"] = "SUCCESS"
                debug_info["test_response"] = test_response.text[:100]
            except Exception as e:
                debug_info["api_test"] = "FAILED"
                debug_info["api_error"] = str(e)[:200]
        else:
            debug_info["api_test"] = "NO_API_KEY"
            
    except ImportError as e:
        debug_info["library_status"] = f"MISSING: {str(e)}"
    
    return debug_info

@app.get("/test/ai")
async def test_ai():
    """Direct AI test endpoint"""
    return await get_real_gemini_response("What is 2+2? Answer only with the number.", "en")

async def optional_auth(authorization: Optional[str] = Header(None)):
    return True

async def get_real_gemini_response(text: str, language: str = "en") -> Dict[str, Any]:
    """REAL Gemini AI integration using official Google library"""
    start_time = time.time()
    
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    
    if not gemini_key or len(gemini_key) < 20:
        logger.error("❌ GEMINI API KEY NOT SET OR INVALID")
        return {
            "text": f"ERROR: Gemini API key not configured. You said: '{text}'",
            "provider": "error",
            "response_time_ms": int((time.time() - start_time) * 1000)
        }
    
    try:
        # Import the NEW Google GenAI library (not google-generativeai)
        from google import genai
        
        logger.info(f"🤖 Making REAL Gemini API call for: '{text[:50]}...'")
        
        # Create client with API key
        client = genai.Client(api_key=gemini_key)
        
        # Prepare prompt
        if language == "es":
            prompt = f"Responde en español: {text}"
        elif language == "fr":
            prompt = f"Répondez en français: {text}"
        else:
            prompt = text
        
        # Make the REAL API call
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        ai_text = response.text.strip()
        response_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ REAL Gemini API success in {response_time}ms")
        
        return {
            "text": ai_text,
            "provider": "gemini-2.5-flash",
            "response_time_ms": response_time
        }
        
    except ImportError as e:
        logger.error(f"❌ Google GenAI library not installed: {e}")
        return {
            "text": f"Library error: google-genai not installed. Install with: pip install google-genai",
            "provider": "library_error",
            "response_time_ms": int((time.time() - start_time) * 1000)
        }
        
    except Exception as e:
        logger.error(f"❌ Gemini API error: {str(e)}")
        response_time = int((time.time() - start_time) * 1000)
        
        return {
            "text": f"Gemini API error: {str(e)[:100]}",
            "provider": "api_error", 
            "response_time_ms": response_time
        }

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth: bool = Depends(optional_auth)):
    """Chat endpoint with REAL Gemini AI integration"""
    start_time = time.time()
    
    try:
        logger.info(f"📨 REAL Chat request: '{request.text[:100]}...'")
        
        # Get REAL AI response
        ai_result = await get_real_gemini_response(request.text, request.language)
        
        total_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Chat completed in {total_time}ms using {ai_result['provider']}")
        
        return ChatResponse(
            ok=True,
            message={"text": ai_result["text"], "role": "assistant"},
            response_time_ms=total_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=ai_result["provider"]
        )
        
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"Chat error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

@app.get("/v1/version")
async def version():
    return {
        "version": "2.3.0",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_time": os.getenv("BUILD_TIME", "unknown"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "gemini_real": True,
        "status": "REAL_AI_INTEGRATION"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
