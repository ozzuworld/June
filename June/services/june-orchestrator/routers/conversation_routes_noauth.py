from fastapi import APIRouter
from pydantic import BaseModel
import os
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["Conversation"])

class ConversationInput(BaseModel):
    text: str
    language: str = "en"

@router.get("/ping")
async def ping():
    return {"ok": True, "service": "june-orchestrator", "status": "healthy"}

@router.post("/conversation") 
async def chat_no_auth(payload: ConversationInput):
    """Test endpoint without authentication"""
    try:
        # Test Gemini AI with correct model name
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "GEMINI_API_KEY not configured"}
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')  # Updated to current model
        
        response = model.generate_content(f"Please respond to this message: {payload.text}")
        
        return {
            "ok": True,
            "message": {
                "text": response.text,
                "role": "assistant"
            }
        }
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"error": f"Chat failed: {str(e)}"}
