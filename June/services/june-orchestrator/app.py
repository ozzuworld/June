# app.py - FIXED with proper auth integration
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

# Import fixed shared auth
from shared.auth import (
    require_user_auth, 
    test_keycloak_connection, 
    get_auth_service,
    AuthError,
    extract_user_id
)

from db.session import engine
from db.models import Base
from middleware.error import unhandled_errors

# Import your routers
from routers.conversation_routes import router as conversation_router

# Set up logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

def _get_allowed_origins() -> list[str]:
    origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
    if origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in origins.split(",") if o.strip()]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting June Orchestrator...")
    
    # Initialize database
    try:
        Base.metadata.create_all(bind=engine.sync_engine)
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
    
    # Test auth configuration
    try:
        auth_service = get_auth_service()
        logger.info("✅ Auth service initialized")
        
        # Test Keycloak connection
        test_result = await test_keycloak_connection()
        if test_result["status"] == "success":
            logger.info("✅ Keycloak connection test passed")
            logger.info(f"   Issuer: {test_result['oidc_endpoints']['issuer']}")
            logger.info(f"   JWKS URI: {test_result['oidc_endpoints']['jwks_uri']}")
        else:
            logger.error(f"❌ Keycloak connection test failed: {test_result['error']}")
    except Exception as e:
        logger.error(f"❌ Auth service initialization failed: {e}")
    
    # Test Gemini API if available
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            logger.info("✅ Gemini AI initialized")
        except Exception as e:
            logger.warning(f"⚠️ Gemini AI initialization failed: {e}")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not set")
    
    logger.info("🎉 June Orchestrator startup complete!")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down June Orchestrator...")

def create_app() -> FastAPI:
    app = FastAPI(
        title="June Orchestrator", 
        version="1.0.0",
        lifespan=lifespan
    )

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

    # ========== DEBUG ENDPOINTS ==========
    
    @app.get("/debug/auth")
    async def debug_auth():
        """Debug endpoint to test Keycloak connection"""
        try:
            result = await test_keycloak_connection()
            return result
        except Exception as e:
            logger.error(f"Debug auth failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "environment": {
                    "KEYCLOAK_URL": os.getenv("KEYCLOAK_URL", "NOT_SET"),
                    "KEYCLOAK_REALM": os.getenv("KEYCLOAK_REALM", "NOT_SET"),
                    "REQUIRED_AUDIENCE": os.getenv("REQUIRED_AUDIENCE", "NOT_SET"),
                }
            }

    @app.get("/debug/env")
    async def debug_env():
        """Debug endpoint to check environment variables"""
        return {
            "auth_config": {
                "KEYCLOAK_URL": os.getenv("KEYCLOAK_URL", "NOT_SET"),
                "KEYCLOAK_REALM": os.getenv("KEYCLOAK_REALM", "NOT_SET"),
                "REQUIRED_AUDIENCE": os.getenv("REQUIRED_AUDIENCE", "NOT_SET"),
                "OIDC_JWKS_URL": os.getenv("OIDC_JWKS_URL", "NOT_SET"),
                "has_client_id": bool(os.getenv("ORCHESTRATOR_CLIENT_ID")),
                "has_client_secret": bool(os.getenv("ORCHESTRATOR_CLIENT_SECRET")),
            },
            "app_config": {
                "has_gemini_key": bool(os.getenv("GEMINI_API_KEY")),
                "has_database_url": bool(os.getenv("DATABASE_URL")),
                "log_level": os.getenv("LOG_LEVEL", "INFO"),
            }
        }

    @app.get("/debug/whoami")
    async def debug_whoami(user_data = require_user_auth):
        """Debug endpoint to test token validation"""
        try:
            user_id = extract_user_id(user_data)
            return {
                "status": "authenticated",
                "user_id": user_id,
                "username": user_data.get("preferred_username"),
                "email": user_data.get("email"),
                "client_id": user_data.get("azp"),
                "audience": user_data.get("aud"),
                "scopes": user_data.get("scope", "").split(),
                "token_claims": {
                    k: v for k, v in user_data.items() 
                    if k in ["sub", "iss", "aud", "exp", "iat", "azp", "scope"]
                }
            }
        except Exception as e:
            logger.error(f"Debug whoami failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Debug failed: {str(e)}"
            )

    # ========== HEALTH ENDPOINTS ==========

    @app.get("/healthz")
    async def health_check():
        """Health check endpoint"""
        return {
            "status": "healthy",
            "service": "june-orchestrator",
            "version": "1.0.0"
        }

    @app.get("/")
    async def root():
        """Root endpoint"""
        return {
            "service": "june-orchestrator", 
            "status": "running",
            "version": "1.0.0"
        }

    # ========== MAIN ROUTERS ==========
    
    # Include conversation router (this handles /v1/chat)
    app.include_router(conversation_router)

    # ========== ERROR HANDLERS ==========
    
    @app.exception_handler(AuthError)
    async def auth_error_handler(request, exc: AuthError):
        """Handle authentication errors"""
        logger.warning(f"Auth error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": f"Authentication failed: {str(exc)}"}
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        """Handle HTTP exceptions with better logging"""
        if exc.status_code == 401:
            logger.warning(f"401 Unauthorized: {exc.detail}")
        elif exc.status_code >= 500:
            logger.error(f"Server error {exc.status_code}: {exc.detail}")
        
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

    return app

app = create_app()