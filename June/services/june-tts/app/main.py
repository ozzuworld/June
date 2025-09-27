import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="June TTS API", version="1.0")

# ----- CORS -----
origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
origins = [o.strip() for o in origins_env.split(",") if o.strip()]
allow_all = "*" in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Routers -----
try:
    from app.routers.standard_tts import router as standard_tts_router
    app.include_router(standard_tts_router)
    logger.info("✅ Standard TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ standard_tts router load warning: {e}")

try:
    from app.routers.tts import router as tts_router
    app.include_router(tts_router)
    logger.info("✅ TTS router loaded")
except Exception as e:
    logger.warning(f"⚠️ tts router load warning: {e}")

try:
    from app.routers.clone import router as clone_router
    app.include_router(clone_router)
    logger.info("✅ Clone router loaded")
except Exception as e:
    logger.warning(f"⚠️ clone router load warning: {e}")

try:
    from app.routers.admin import router as admin_router  # healthz, voices
    app.include_router(admin_router)
    logger.info("✅ Admin router loaded")
except Exception as e:
    logger.warning(f"⚠️ admin router load warning: {e}")

# ----- Startup warmup (non-fatal if it fails) -----
@app.on_event("startup")
async def _startup() -> None:
    try:
        from app.core.openvoice_engine import warmup_models
        warmup_models()
        logger.info("✅ TTS models warmed up successfully")
    except Exception as e:
        logger.warning(f"⚠️ warmup skipped: {e}")

# ----- Root -----
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "June TTS API",
        "version": "1.0",
        "endpoints": {
            "standard_tts": "/v1/tts",
            "voice_cloning": "/tts/generate or /clone/voice",
            "health_check": "/healthz",
            "voices": "/v1/voices",
            "status": "/v1/status"
        }
    }
