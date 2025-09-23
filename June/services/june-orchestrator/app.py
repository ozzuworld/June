from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from db.session import engine
from db.models import Base
from middleware.error import unhandled_errors
from routers.conversation_routes import router as conversation_router


def _get_allowed_origins() -> list[str]:
    import os
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS required (comma-separated).")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB migrations bootstrap (simple create_all for now)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # nothing to tear down; httpx clients are per-request via DI


def create_app() -> FastAPI:
    app = FastAPI(title="June Orchestrator", version="2.0.0", lifespan=lifespan)

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

    # Routers
    app.include_router(conversation_router)

    return app


app = create_app()
