from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.routers.tts import router as tts_router
from app.core.openvoice_engine import warmup_models


def _allowed_origins() -> list[str]:
    import os
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS required (comma-separated).")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load/Memoize models onto GPU/CPU so first request is hot
    warmup_models()
    yield
    # If you later memoize multiple language packs or alloc streams, release here.


def create_app() -> FastAPI:
    app = FastAPI(title="June TTS", version="2.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(tts_router)
    return app


app = create_app()
