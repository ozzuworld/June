#!/usr/bin/env python3
"""
June Orchestrator - Clean Version
Simple, minimal FastAPI service for chat functionality
"""

import os
import logging
import time
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import requests
from jose import jwt, JWTError

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Environment variables
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://idp.allsafe.world")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "allsafe")
REQUIRED_AUDIENCE = os.getenv("REQUIRED_AUDIENCE", "june-orchestrator")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# FastAPI app
app = FastAPI(
    title="June Orchestrator",
    description="Clean, simple AI chat orchestrator",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer(auto_error=False)

# Models
class ChatRequest(BaseModel):
    text: str
    language: Optional[str] = "en"
    metadata: Optional[Dict[str, Any]] = None

class ChatResponse(BaseModel):
    ok: bool = True
    message: Dict[str, str]
    response_time_ms: Optional[int] = None

# Authentication
def get_keycloak_public_key():
    """Get public key from Keycloak for token verification"""
    try:
        jwks_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get Keycloak public key: {e}")
        return None

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token from Keycloak"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required"
        )
    
    try:
        # For now, we'll do basic validation
        # In production, properly verify with Keycloak public key
        token = credentials.credentials
        
        # Basic token validation (customize as needed)
        if not token or len(token.split('.')) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format"
            )
        
        # For now, return a basic user context
        # In production, decode and validate the JWT properly
        return {
            "user_id": "authenticated_user",
            "username": "user",
            "token": token
        }
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

# AI Response Generation
def generate_ai_response(user_text: str) -> str:
    """Generate AI response using Gemini or fallback logic"""
    
    # Try Gemini API if available
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            response = model.generate_content(f"Respond naturally to: {user_text}")
            return response.text
            
        except Exception as e:
            logger.warning(f"Gemini API failed, using fallback: {e}")
    
    # Fallback responses
    user_lower = user_text.lower()
    
    if any(word in user_lower for word in ['hello', 'hi', 'hey']):
        return "Hello! I'm OZZU, your AI assistant. How can I help you today?"
    
    elif any(word in user_lower for word in ['weather', 'temperature']):
        return "I'd be happy to help with weather information, but I don't have access to current weather data yet. Is there anything else I can help you with?"
    
    elif any(word in user_lower for word in ['time', 'date']):
        return f"I can see it's currently around {time.strftime('%I:%M %p')} on {time.strftime('%B %d, %Y')}. How can I assist you?"
    
    elif any(word in user_lower for word in ['help', 'what can you do']):
        return "I'm here to help! I can answer questions, have conversations, and assist with various tasks. What would you like to know or discuss?"
    
    else:
        return f"I understand you're asking about: '{user_text}'. I'm here to help! What would you like to know more about?"

# Routes
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "june-orchestrator",
        "version": "2.0.0",
        "status": "running",
        "description": "Clean, simple AI chat orchestrator",
        "endpoints": {
            "chat": "/v1/chat",
            "health": "/healthz"
        }
    }

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-orchestrator",
        "version": "2.0.0",
        "timestamp": int(time.time())
    }

@app.get("/debug/routes")
async def debug_routes():
    """Debug endpoint to list all routes"""
    routes = []
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            routes.append({
                "path": route.path,
                "methods": list(route.methods)
            })
    return {"routes": routes}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_context: Dict = Depends(verify_token)):
    """Main chat endpoint - simple and clean"""
    
    start_time = time.time()
    
    try:
        # Validate input
        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Text message is required"
            )
        
        user_text = request.text.strip()
        logger.info(f"💬 Chat request from {user_context.get('username', 'user')}: '{user_text[:50]}...'")
        
        # Generate AI response
        ai_response = generate_ai_response(user_text)
        
        response_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Generated response in {response_time}ms")
        
        return ChatResponse(
            ok=True,
            message={
                "text": ai_response,
                "role": "assistant"
            },
            response_time_ms=response_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    logger.warning(f"404 Not Found: {request.url}")
    return {
        "detail": "Not Found",
        "available_endpoints": {
            "chat": "/v1/chat",
            "health": "/healthz",
            "debug": "/debug/routes"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)