# app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import logging, os

from db.session import engine
from db.models import Base
from middleware.error import unhandled_errors

# ⬇️ import your routers
from routers.conversation_routes import router as conversation_router
from media_apis import media_router
from voice_ws import voice_router
from routers.conversation_routes import router as conversation_router
app.include_router(conversation_router) 

logger = logging.getLogger(__name__)

def _get_allowed_origins() -> list[str]:
    origins = os.getenv("ALLOWED_ORIGINS", "*")
    if origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in origins.split(",") if o.strip()]

def create_app() -> FastAPI:
    app = FastAPI(title="June Orchestrator", version="1.0.0")

    # DB init (optional autocrate)
    Base.metadata.create_all(bind=engine.sync_engine)

    # Error middleware
    app.middleware("http")(unhandled_errors)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Health
    @app.get("/")
    async def root():
        return {"service": "june-orchestrator", "ok": True}

    # ⬇️ mount routers
    app.include_router(conversation_router)    # should define /v1/chat
    app.include_router(media_router)           # /v1/media/...
    app.include_router(voice_router)           # whatever prefix voice_ws defines

    # Optional: list routes on startup (helps debug 404s)
    @app.on_event("startup")
    async def log_routes():
        routes = []
        for r in app.routes:
            methods = getattr(r, "methods", [])
            path = getattr(r, "path", None)
            for m in methods or []:
                if m != "HEAD":
                    routes.append(f"{m} {path}")
        for line in sorted(routes):
            logger.info("ROUTE %s", line)

    return app

app = create_app()
