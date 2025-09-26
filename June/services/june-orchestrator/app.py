from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import time
import os
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="OZZU June Orchestrator", version="2.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class ChatRequest(BaseModel):
    text: str
    language: Optional[str] = "en"
    metadata: Optional[Dict[str, Any]] = {}

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int

@app.get("/")
async def root():
    return {"service": "OZZU June Orchestrator", "version": "2.0.0", "status": "healthy"}

@app.get("/healthz")
async def health_check():
    return {"status": "healthy"}

@app.get("/debug/routes")
async def debug_routes():
    routes = []
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            routes.append({"path": route.path, "methods": list(route.methods)})
    return {"routes": routes}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start_time = time.time()
    
    try:
        logger.info(f"Ì≥® Chat request: {request.text[:50]}...")
        
        # Try Gemini AI
        try:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(f"You are OZZU, a helpful AI assistant. Respond to: {request.text}")
            ai_response = response.text
            logger.info("‚úÖ Gemini response generated")
        except Exception as e:
            logger.warning(f"Gemini failed: {e}")
            ai_response = f"Hello! I'm OZZU, your AI assistant. You said: '{request.text}'. How can I help you today?"
        
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time
        )
        
    except Exception as e:
        logger.error(f"‚ùå Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        return ChatResponse(
            ok=False,
            message={"text": f"Sorry, I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
