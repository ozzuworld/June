#!/bin/bash
# deploy-orchestrator-tts.sh
# Deploy enhanced orchestrator with external TTS integration

set -euo pipefail

echo "🚀 Deploying June Orchestrator with External TTS Integration"
echo "==========================================================="

# Configuration
PROJECT_ID="main-buffer-469817-v7"
REGION="us-central1"
CLUSTER_NAME="june-unified-cluster"
NAMESPACE="june-services"
IMAGE_TAG="v3.1.0-tts-$(date +%s)"
REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/june"

# Your external TTS service details
TTS_EXTERNAL_URL="${TTS_EXTERNAL_URL:-http://YOUR_TTS_VM_IP:8000}"  # Update this!

log() {
    echo -e "\033[0;32m[$(date +'%H:%M:%S')] $1\033[0m"
}

error() {
    echo -e "\033[0;31m[$(date +'%H:%M:%S')] ERROR: $1\033[0m"
    exit 1
}

# Check we're in the right directory
if [ ! -f "June/services/june-orchestrator/app.py" ]; then
    error "Please run from project root directory"
fi

cd June/services/june-orchestrator

# Step 1: Create the TTS client
log "Creating TTS client..."
cat > tts_client.py << 'EOF'
# TTS Client for external TTS service
import os
import base64
import time
import asyncio
from typing import Optional, Dict, Any
import logging
import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class TTSClient:
    def __init__(self):
        self.tts_url = os.getenv("TTS_SERVICE_URL", "http://localhost:8000")
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        self.default_voice = os.getenv("TTS_DEFAULT_VOICE", "default")
        self.default_speed = float(os.getenv("TTS_DEFAULT_SPEED", "1.0"))
        self.default_language = os.getenv("TTS_DEFAULT_LANGUAGE", "EN")
        
    async def synthesize_speech(
        self,
        text: str,
        voice: str = None,
        speed: float = None,
        language: str = None,
        reference_audio_b64: Optional[str] = None
    ) -> Dict[str, Any]:
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        voice = voice or self.default_voice
        speed = speed or self.default_speed
        language = language or self.default_language
        
        try:
            if reference_audio_b64:
                audio_data = await self._synthesize_with_cloning(
                    text, reference_audio_b64, speed, language
                )
            else:
                audio_data = await self._synthesize_standard(
                    text, voice, speed, language
                )
            
            return {
                "audio_data": audio_data,
                "content_type": "audio/wav",
                "size_bytes": len(audio_data),
                "voice": voice,
                "speed": speed,
                "language": language,
                "generated_at": time.time()
            }
            
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")
    
    async def _synthesize_standard(self, text: str, voice: str, speed: float, language: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.tts_url}/v1/tts",
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language,
                    "format": "wav"
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                raise Exception(f"TTS service returned {response.status_code}: {response.text}")
            
            return response.content
    
    async def _synthesize_with_cloning(self, text: str, reference_audio_b64: str, speed: float, language: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.tts_url}/tts/generate",
                json={
                    "text": text,
                    "reference_b64": reference_audio_b64,
                    "language": language.lower(),
                    "speed": speed,
                    "volume": 1.0,
                    "pitch": 0.0,
                    "format": "wav"
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                raise Exception(f"TTS cloning service returned {response.status_code}: {response.text}")
            
            return response.content
    
    async def get_status(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.tts_url}/healthz")
                
                if response.status_code == 200:
                    return {"available": True, "url": self.tts_url}
                else:
                    return {"available": False, "error": f"Status check failed: {response.status_code}"}
                    
        except Exception as e:
            logger.warning(f"TTS status check failed: {e}")
            return {"available": False, "error": str(e)}

_tts_client: Optional[TTSClient] = None

def get_tts_client() -> TTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client
EOF

# Step 2: Update the main app.py with TTS integration
log "Updating app.py with TTS integration..."
cat > app.py << 'EOF'
# June/services/june-orchestrator/app.py
# Enhanced orchestrator with external TTS integration

import os
import time
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Gemini imports
USING_NEW_SDK = False
try:
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
    logger.info("✅ Using new Google GenAI SDK")
except ImportError:
    try:
        import google.generativeai as genai
        USING_NEW_SDK = False
        logger.info("✅ Using legacy google-generativeai library")
    except ImportError:
        logger.error("❌ No Gemini library found")
        genai = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from tts_client import get_tts_client

app = FastAPI(title="June Orchestrator", version="3.1.0", description="June AI Platform Orchestrator with TTS integration")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class AudioConfig(BaseModel):
    voice: Optional[str] = Field(default="default")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    language: Optional[str] = Field(default="EN")
    reference_audio_b64: Optional[str] = Field(default=None)

class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1000, ge=1, le=4000)
    include_audio: Optional[bool] = Field(default=False)
    audio_config: Optional[AudioConfig] = Field(default=None)

class AudioData(BaseModel):
    data: str = Field(...)
    content_type: str = Field(default="audio/wav")
    size_bytes: int = Field(...)
    voice: str = Field(...)
    speed: float = Field(...)
    language: str = Field(...)

class ChatResponse(BaseModel):
    ok: bool
    message: Dict[str, str]
    response_time_ms: int
    conversation_id: Optional[str] = None
    ai_provider: str = "gemini"
    audio: Optional[AudioData] = Field(default=None)

class GeminiService:
    def __init__(self):
        self.model = None
        self.client = None
        self.api_key = None
        self.is_available = False
        self.initialize()
    
    def initialize(self):
        try:
            self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
            
            if not self.api_key or len(self.api_key) < 30:
                logger.warning("❌ GEMINI_API_KEY not set or invalid")
                return False
            
            if not genai:
                logger.warning("❌ No Gemini library available")
                return False
            
            if USING_NEW_SDK:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ New GenAI SDK configured")
                
                try:
                    response = self.client.models.generate_content(model='gemini-1.5-flash', contents='Say "Hello"')
                    if response and response.text:
                        self.is_available = True
                        return True
                except Exception:
                    try:
                        response = self.client.models.generate_content(model='gemini-2.0-flash-exp', contents='Say "Hello"')
                        if response and response.text:
                            self.is_available = True
                            return True
                    except Exception as e:
                        logger.warning(f"❌ New SDK test failed: {e}")
                        return False
            else:
                genai.configure(api_key=self.api_key)
                try:
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    test_response = self.model.generate_content("Say 'Hello'")
                    if test_response and test_response.text:
                        self.is_available = True
                        return True
                except Exception as e:
                    logger.error(f"❌ Legacy SDK test failed: {e}")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            return False
    
    async def generate_response(self, text: str, language: str = "en", temperature: float = 0.7) -> tuple[str, str]:
        if not self.is_available:
            return self._get_fallback_response(text, language), "fallback"
        
        try:
            system_prompts = {
                "en": "You are JUNE, a helpful AI assistant. Provide clear, accurate, and helpful responses.",
                "es": "Eres JUNE, un asistente de IA útil. Proporciona respuestas claras, precisas y útiles en español.",
                "fr": "Vous êtes JUNE, un assistant IA utile. Fournissez des réponses claires, précises et utiles en français."
            }
            
            system_prompt = system_prompts.get(language, system_prompts["en"])
            full_prompt = f"{system_prompt}\n\nUser: {text}\n\nAssistant:"
            
            if USING_NEW_SDK and self.client:
                try:
                    response = self.client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=1000)
                    )
                except Exception:
                    response = self.client.models.generate_content(
                        model='gemini-2.0-flash-exp',
                        contents=full_prompt,
                        config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=1000)
                    )
                
                if response and response.text:
                    return response.text.strip(), "gemini-new-sdk"
            else:
                if self.model:
                    generation_config = genai.types.GenerationConfig(temperature=temperature, max_output_tokens=1000)
                    response = self.model.generate_content(full_prompt, generation_config=generation_config)
                    
                    if response and response.text:
                        return response.text.strip(), "gemini-legacy"
            
            return self._get_fallback_response(text, language), "fallback"
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return self._get_fallback_response(text, language), "fallback"
    
    def _get_fallback_response(self, text: str, language: str) -> str:
        responses = {
            "en": {"greeting": "Hello! I'm JUNE, your AI assistant. How can I help you today?", "default": f"I understand you're asking about '{text}'. I'm here to help you."},
            "es": {"greeting": "¡Hola! Soy JUNE, tu asistente de IA. ¿Cómo puedo ayudarte hoy?", "default": f"Entiendo que preguntas sobre '{text}'. Estoy aquí para ayudarte."},
            "fr": {"greeting": "Bonjour! Je suis JUNE, votre assistant IA. Comment puis-je vous aider aujourd'hui?", "default": f"Je comprends que vous demandez à propos de '{text}'. Je suis là pour vous aider."}
        }
        
        lang_responses = responses.get(language, responses["en"])
        text_lower = text.lower()
        if any(word in text_lower for word in ["hello", "hi", "hey", "hola", "bonjour"]):
            return lang_responses["greeting"]
        return lang_responses["default"]

gemini_service = GeminiService()

@app.get("/")
async def root():
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    
    return {
        "service": "June Orchestrator",
        "version": "3.1.0",
        "status": "healthy",
        "features": {"ai_chat": gemini_service.is_available, "text_to_speech": tts_status.get("available", False)},
        "tts_service_url": os.getenv("TTS_SERVICE_URL", "not_configured"),
        "endpoints": {"health": "/healthz", "chat": "/v1/chat", "tts_status": "/v1/tts/status"}
    }

@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "service": "june-orchestrator", "version": "3.1.0", "timestamp": time.time()}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start_time = time.time()
    
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        ai_response, provider = await gemini_service.generate_response(request.text.strip(), request.language, request.temperature)
        
        response_time = int((time.time() - start_time) * 1000)
        
        chat_response = ChatResponse(
            ok=True,
            message={"text": ai_response, "role": "assistant"},
            response_time_ms=response_time,
            conversation_id=f"conv-{int(time.time())}",
            ai_provider=provider
        )
        
        if request.include_audio:
            try:
                tts_client = get_tts_client()
                audio_config = request.audio_config or AudioConfig()
                
                audio_result = await tts_client.synthesize_speech(
                    text=ai_response,
                    voice=audio_config.voice,
                    speed=audio_config.speed,
                    language=audio_config.language,
                    reference_audio_b64=audio_config.reference_audio_b64
                )
                
                audio_b64 = base64.b64encode(audio_result["audio_data"]).decode('utf-8')
                
                chat_response.audio = AudioData(
                    data=audio_b64,
                    content_type=audio_result["content_type"],
                    size_bytes=audio_result["size_bytes"],
                    voice=audio_result["voice"],
                    speed=audio_result["speed"],
                    language=audio_result["language"]
                )
                
            except Exception as e:
                logger.error(f"❌ TTS generation failed: {e}")
        
        return chat_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        
        return ChatResponse(
            ok=False,
            message={"text": f"I apologize, but I encountered an error: {str(e)}", "role": "error"},
            response_time_ms=response_time,
            ai_provider="error"
        )

@app.get("/v1/tts/status")
async def tts_status():
    tts_client = get_tts_client()
    return await tts_client.get_status()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting June Orchestrator v3.1.0 with external TTS integration")
    logger.info(f"TTS Service URL: {os.getenv('TTS_SERVICE_URL', 'not_configured')}")
    
    if gemini_service.is_available:
        logger.info("✅ Gemini service ready")
    else:
        logger.warning("⚠️ Gemini service not ready")
    
    tts_client = get_tts_client()
    tts_status = await tts_client.get_status()
    if tts_status.get("available", False):
        logger.info("✅ External TTS service ready")
    else:
        logger.warning("⚠️ External TTS service not reachable")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
EOF

# Step 3: Update requirements.txt
log "Updating requirements.txt..."
cat > requirements.txt << 'EOF'
fastapi==0.111.0
uvicorn[standard]==0.30.1
pydantic==2.8.2
httpx==0.27.0
google-genai>=1.0.0
EOF

# Step 4: Ensure Dockerfile is correct
log "Updating Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY tts_client.py .

# Create non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
EOF

# Step 5: Build and push image
log "Building orchestrator image with TTS integration..."
FULL_IMAGE="${REGISTRY}/june-orchestrator:${IMAGE_TAG}"

docker build -t "$FULL_IMAGE" .
docker tag "$FULL_IMAGE" "${REGISTRY}/june-orchestrator:latest"

log "Pushing image to registry..."
docker push "$FULL_IMAGE"
docker push "${REGISTRY}/june-orchestrator:latest"

# Step 6: Create deployment YAML with external TTS configuration
log "Creating deployment configuration..."
cat > orchestrator-tts-deployment.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: ${NAMESPACE}
  labels:
    app: june-orchestrator
    version: "3.1.0-tts"
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      app: june-orchestrator
  template:
    metadata:
      labels:
        app: june-orchestrator
        version: "3.1.0-tts"
    spec:
      serviceAccountName: june-secret-manager
      containers:
        - name: orchestrator
          image: ${FULL_IMAGE}
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          
          env:
            # AI Configuration
            - name: GEMINI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: june-secrets
                  key: gemini-api-key
                  optional: true
            
            # External TTS Service Configuration
            - name: TTS_SERVICE_URL
              value: "${TTS_EXTERNAL_URL}"
            - name: TTS_DEFAULT_VOICE
              value: "default"
            - name: TTS_DEFAULT_SPEED
              value: "1.0"
            - name: TTS_DEFAULT_LANGUAGE
              value: "EN"
            
            # Authentication
            - name: KEYCLOAK_URL
              value: "https://idp.allsafe.world"
            - name: KEYCLOAK_REALM
              value: "allsafe"
            
            # Application
            - name: LOG_LEVEL
              value: "INFO"
            - name: ENVIRONMENT
              value: "production"
            - name: PORT
              value: "8080"
          
          resources:
            requests:
              cpu: "300m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 10
            failureThreshold: 3
      
      restartPolicy: Always
      terminationGracePeriodSeconds: 60

---
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator
  namespace: ${NAMESPACE}
  labels:
    app: june-orchestrator
  annotations:
    cloud.google.com/neg: '{"ingress": true}'
spec:
  type: ClusterIP
  selector:
    app: june-orchestrator
  ports:
    - name: http
      port: 80
      targetPort: 8080
      protocol: TCP
EOF

# Step 7: Deploy to Kubernetes
log "Deploying to Kubernetes..."
kubectl apply -f orchestrator-tts-deployment.yaml

# Step 8: Wait for rollout
log "Waiting for deployment rollout..."
kubectl rollout status deployment/june-orchestrator -n "$NAMESPACE" --timeout=300s

# Step 9: Verify deployment
log "Verifying deployment..."
kubectl get pods -n "$NAMESPACE" -l app=june-orchestrator

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🔍 Check status:"
echo "   kubectl logs -n ${NAMESPACE} deployment/june-orchestrator -f"
echo ""
echo "🧪 Test endpoints:"
echo "   curl https://api.allsafe.world/healthz"
echo "   curl https://api.allsafe.world/v1/tts/status"
echo ""
echo "⚠️  IMPORTANT: Update TTS_EXTERNAL_URL to your VM's IP:"
echo "   export TTS_EXTERNAL_URL=\"http://YOUR_TTS_VM_IP:8000\""
echo "   Then re-run this script"
EOF

chmod +x deploy-orchestrator-tts.sh

# Step 3: Update environment configuration
log "Creating environment configuration..."
cat > .env.example << EOF
# External TTS Service Configuration
TTS_SERVICE_URL=http://YOUR_TTS_VM_IP:8000  # UPDATE THIS!
TTS_DEFAULT_VOICE=default
TTS_DEFAULT_SPEED=1.0
TTS_DEFAULT_LANGUAGE=EN

# AI Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# Application
LOG_LEVEL=INFO
ENVIRONMENT=production
PORT=8080
EOF

echo ""
echo "🎯 NEXT STEPS:"
echo "=============="
echo ""
echo "1. UPDATE YOUR TTS VM IP:"
echo "   export TTS_EXTERNAL_URL=\"http://YOUR_TTS_VM_IP:8000\""
echo ""
echo "2. DEPLOY THE ORCHESTRATOR:"
echo "   ./deploy-orchestrator-tts.sh"
echo ""
echo "3. VERIFY TTS CONNECTIVITY:"
echo "   curl https://api.allsafe.world/v1/tts/status"
echo ""
echo "4. TEST CHAT WITH AUDIO:"
echo "   curl -X POST https://api.allsafe.world/v1/chat \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"text\":\"Hello\", \"include_audio\":true}'"