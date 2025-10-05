"""
Entry point for the simplified June TTS service.

This version removes experimental and research‑oriented features and focuses on
providing basic text‑to‑speech and tone‑colour voice cloning functionality
according to the OpenVoice V2 guidelines. Only the base MeloTTS model and the
ToneColorConverter are loaded and exposed via FastAPI endpoints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import tts as tts_router
from .routers import clone as clone_router
from .routers import admin as admin_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="June TTS Service",
        description=(
            "A lightweight wrapper around the OpenVoice V2 models providing "
            "standard text‑to‑speech and voice cloning via tone colour conversion."
        ),
        version="0.1.0",
    )

    # Enable CORS for all origins. In a production environment you should
    # restrict allowed origins to known front‑ends or client applications.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(tts_router.router, prefix="/v1")
    app.include_router(clone_router.router, prefix="/v1")
    app.include_router(admin_router.router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """Root endpoint with basic information about the service."""
        return {
            "service": "june-tts",
            "version": app.version,
            "description": app.description,
        }

    return app


app = create_app()