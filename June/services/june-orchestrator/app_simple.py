from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from routers.conversation_routes_noauth import router as conversation_router

app = FastAPI(title="June Orchestrator", version="1.0.0")

# CORS
origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
async def health():
    return {"status": "healthy"}

app.include_router(conversation_router)
