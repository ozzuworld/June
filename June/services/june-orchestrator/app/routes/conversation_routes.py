"""Conversation routes"""
from fastapi import APIRouter
conversation_bp = APIRouter()

@conversation_bp.get("/health")
async def conversation_health():
    return {"status": "ok", "service": "conversation"}