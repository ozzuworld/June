from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import os
from contextlib import asynccontextmanager

# Import your existing modules
from models import ChatRequest, ChatResponse, ConversationRequest, ConversationResponse
from enhanced_conversation_manager import EnhancedConversationManager
from tts_service import TTSService
from token_service import TokenService
from external_tts_client import ExternalTTSClient
from media_apis import MediaAPI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize services
conversation_manager = EnhancedConversationManager()
tts_service = TTSService()
token_service = TokenService()
external_tts = ExternalTTSClient()
media_api = MediaAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting June Orchestrator with all services...")
    yield
    # Shutdown
    logger.info("Shutting down June Orchestrator...")

app = FastAPI(
    title="June Orchestrator",
    version="2.0.0",
    description="Full-featured orchestrator with TTS, conversation management, and authentication",
    lifespan=lifespan
)

# CORS middleware with your settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication dependency
async def get_current_user(request: Request):
    """Get current user from token - uses your existing TokenService"""
    try:
        return await token_service.get_current_user(request)
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        return None  # Allow unauthenticated for now

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "June Orchestrator", 
        "version": "2.0.0", 
        "status": "healthy",
        "features": ["chat", "tts", "stt", "media", "auth"]
    }

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.get("/debug/routes")
async def debug_routes():
    """Debug endpoint to list all routes"""
    routes = []
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            routes.append({"path": route.path, "methods": list(route.methods)})
    return {"routes": routes}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    current_user = Depends(get_current_user)
):
    """Main chat endpoint using your enhanced conversation manager"""
    try:
        logger.info(f"Chat request from user: {getattr(current_user, 'id', 'anonymous')}")
        logger.info(f"Message: {request.text[:100]}...")
        
        # Use your enhanced conversation manager
        response = await conversation_manager.process_conversation(
            text=request.text,
            user_id=getattr(current_user, 'id', None),
            language=getattr(request, 'language', 'en'),
            metadata=getattr(request, 'metadata', {})
        )
        
        return ChatResponse(
            ok=True,
            message={"text": response.message, "role": "assistant"},
            response_time_ms=response.response_time_ms,
            conversation_id=getattr(response, 'conversation_id', None),
            audio_url=getattr(response, 'audio_url', None)
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return ChatResponse(
            ok=False,
            message={"text": f"Sorry, I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=0
        )

@app.post("/v1/conversation", response_model=ConversationResponse)
async def conversation_endpoint(
    request: ConversationRequest,
    current_user = Depends(get_current_user)
):
    """Full conversation endpoint with TTS support"""
    try:
        # Process conversation with TTS if requested
        response = await conversation_manager.process_conversation_with_tts(
            request=request,
            user_id=getattr(current_user, 'id', None)
        )
        return response
        
    except Exception as e:
        logger.error(f"Conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/tts")
async def text_to_speech(
    request: dict,
    current_user = Depends(get_current_user)
):
    """Text-to-speech endpoint using your TTS service"""
    try:
        audio_response = await tts_service.synthesize(
            text=request.get("text"),
            voice_id=request.get("voice_id"),
            language=request.get("language", "en")
        )
        return audio_response
        
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/media/upload")
async def upload_media(
    request: Request,
    current_user = Depends(get_current_user)
):
    """Media upload endpoint using your MediaAPI"""
    try:
        response = await media_api.upload_media(request)
        return response
        
    except Exception as e:
        logger.error(f"Media upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
