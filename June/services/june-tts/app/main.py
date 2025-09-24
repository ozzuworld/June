import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    from app.routers.tts import router as tts_router
    app.include_router(tts_router)
except Exception as e:
    print("⚠️ tts router load warning:", e)

try:
    from app.routers.admin import router as admin_router  # healthz, voices
    app.include_router(admin_router)
except Exception as e:
    print("⚠️ admin router load warning:", e)

# ----- Startup warmup (non-fatal if it fails) -----
@app.on_event("startup")
async def _startup() -> None:
    try:
        from app.core.openvoice_engine import warmup_models
        warmup_models()
    except Exception as e:
        print("⚠️ warmup skipped:", e)

# ----- Root -----
@app.get("/")
def root():
    return {"status": "ok"}
