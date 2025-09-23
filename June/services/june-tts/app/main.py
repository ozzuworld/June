from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings
from app.core.openvoice_engine import engine
from app.routers import tts, clone
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting OpenVoice API...")
    try:
        await engine.initialize()
        print("✅ OpenVoice API started successfully")
    except Exception as e:
        print(f"❌ Failed to start OpenVoice API: {e}")
        raise
    yield
    # Shutdown
    print("🛑 OpenVoice API shutting down")

app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="OpenVoice TTS and Voice Cloning API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Include routers
app.include_router(tts.router, prefix="/api/v1")
app.include_router(clone.router, prefix="/api/v1")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "OpenVoice API is running",
        "version": settings.api_version,
        "docs": "/docs",
        "endpoints": {
            "tts": "/api/v1/tts/generate",
            "clone": "/api/v1/clone/voice",
            "status": "/api/v1/tts/status"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "OpenVoice API",
        "version": settings.api_version,
        "engine_status": "ready" if engine.converter else "initializing"
    }

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
