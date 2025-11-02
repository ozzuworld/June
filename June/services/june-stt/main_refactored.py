#!/usr/bin/env python3
"""June STT Enhanced - SOTA Voice AI Optimization - Refactored Architecture"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from services.audio_processor import AudioProcessor
from routers import transcription_routes, health_routes, debug_routes

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt")

# Global services
audio_processor: AudioProcessor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    global audio_processor
    
    logger.info("🚀 June STT Enhanced - SOTA VOICE AI OPTIMIZATION - REFACTORED")
    logger.info("🎯 COMPETITIVE FEATURES: Ultra-fast partials + Aggressive streaming + Sub-700ms pipeline")
    logger.info("💪 REFACTORED: Modular architecture + Improved maintainability + Better performance")
    
    try:
        # Initialize audio processor
        audio_processor = AudioProcessor()
        await audio_processor.initialize()
        
        # Inject dependencies into routers
        health_routes.update_global_stats(
            audio_processor.room_manager.connected if audio_processor.room_manager else False,
            audio_processor.processed_utterances,
            audio_processor.partial_processor.active_tasks.__len__()
        )
        
        debug_routes.inject_dependencies(
            audio_processor.utterance_manager,
            audio_processor.room_manager,
            audio_processor.partial_processor
        )
        
        logger.info("✅ SOTA: All services initialized with refactored architecture")
        
    except Exception as e:
        logger.error(f"❌ Service initialization failed: {e}")
        raise
    
    yield
    
    # Cleanup
    logger.info("🧹 SOTA: Shutting down services")
    if audio_processor:
        await audio_processor.cleanup()

# Create FastAPI app
app = FastAPI(
    title="June STT - SOTA Voice AI Optimization (Refactored)",
    version="7.1.0-sota-refactored",
    description="Ultra-responsive partial transcripts + Sub-700ms pipeline + Modular architecture",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(transcription_routes.router, prefix="/v1")
app.include_router(health_routes.router)
app.include_router(debug_routes.router, prefix="/debug")

# Add periodic stats update
@app.on_event("startup")
async def update_stats_periodically():
    """Periodically update stats in health routes"""
    async def stats_updater():
        while True:
            try:
                if audio_processor:
                    health_routes.update_global_stats(
                        audio_processor.room_manager.connected if audio_processor.room_manager else False,
                        audio_processor.processed_utterances,
                        len(audio_processor.partial_processor.active_tasks)
                    )
                await asyncio.sleep(5.0)  # Update every 5 seconds
            except Exception as e:
                logger.debug(f"Stats update error: {e}")
                await asyncio.sleep(10.0)
    
    asyncio.create_task(stats_updater())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
