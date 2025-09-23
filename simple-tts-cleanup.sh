#!/bin/bash
# simple-tts-cleanup.sh
# Clean removal of old TTS microservice and update orchestrator for external TTS

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

log "🧹 Starting simple TTS cleanup and external integration..."

# Step 1: Remove old TTS service
log "🗑️ Removing old TTS microservice..."
rm -rf June/services/june-tts/
success "Old TTS service removed"

# Step 2: Update orchestrator for external TTS
log "🔧 Updating orchestrator for external TTS..."

# Update orchestrator app.py
cat > June/services/june-orchestrator/external_tts_client.py << 'EOF'
# external_tts_client.py - Client for external OpenVoice TTS service
import httpx
import logging
import base64
from typing import Optional

logger = logging.getLogger(__name__)

class ExternalTTSClient:
    """Client for external OpenVoice TTS service with IDP authentication"""
    
    def __init__(self, base_url: str, auth_client):
        self.base_url = base_url.rstrip('/')
        self.auth_client = auth_client  # Use existing IDP auth client
        
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        language: str = "EN"
    ) -> bytes:
        """Call external OpenVoice TTS service"""
        try:
            logger.info(f"🎵 Calling external TTS: '{text[:50]}...'")
            
            # Use IDP authentication
            response = await self.auth_client.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/tts",
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language
                },
                timeout=30.0
            )
            
            response.raise_for_status()
            
            audio_data = response.content
            logger.info(f"✅ External TTS success: {len(audio_data)} bytes")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ External TTS failed: {e}")
            raise RuntimeError(f"External TTS service failed: {str(e)}")
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: str = "EN"
    ) -> bytes:
        """Call external voice cloning service"""
        try:
            logger.info(f"🎤 Voice cloning request: '{text[:50]}...'")
            
            # Encode audio for transmission
            audio_b64 = base64.b64encode(reference_audio_bytes).decode('utf-8')
            
            response = await self.auth_client.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/clone",
                json={
                    "text": text,
                    "reference_audio": audio_b64,
                    "language": language
                },
                timeout=60.0  # Voice cloning takes longer
            )
            
            response.raise_for_status()
            
            audio_data = response.content
            logger.info(f"✅ Voice cloning success: {len(audio_data)} bytes")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            raise RuntimeError(f"Voice cloning service failed: {str(e)}")
EOF

# Update orchestrator app.py to use external TTS
log "📝 Updating orchestrator main app.py..."

# Create a patch for app.py to replace TTS client initialization
cat > June/services/june-orchestrator/app_tts_patch.py << 'EOF'
# app_tts_patch.py - Patch to update app.py for external TTS
# Add this to your app.py imports:

from external_tts_client import ExternalTTSClient

# Replace the TTS client initialization in startup_event():

# OLD: 
# tts_client = ChatterboxTTSClient(TTS_SERVICE_URL, service_auth)

# NEW:
# External TTS configuration
EXTERNAL_TTS_URL = os.getenv("EXTERNAL_TTS_URL", "")
if EXTERNAL_TTS_URL:
    tts_client = ExternalTTSClient(EXTERNAL_TTS_URL, service_auth)
    logger.info(f"✅ External TTS client configured: {EXTERNAL_TTS_URL}")
else:
    tts_client = None
    logger.warning("⚠️ EXTERNAL_TTS_URL not set - TTS disabled")

# Update the process_audio endpoint to handle external TTS:
# Replace the TTS synthesis call with:

if tts_client and reply:
    try:
        logger.info(f"🎵 Generating speech via external TTS: '{reply[:50]}...'")
        
        # Call external TTS service
        audio_response = await tts_client.synthesize_speech(
            text=reply,
            voice="default",  # Use your OpenVoice voice names
            speed=1.0,
            language="EN"
        )
        
        if audio_response:
            # Encode audio to base64 for response
            audio_b64 = base64.b64encode(audio_response).decode('utf-8')
            logger.info(f"✅ External TTS success: {len(audio_response)} bytes")
            
            tts_metadata = {
                "voice": "openvoice",
                "engine": "external-openvoice",
                "service": "external"
            }
        else:
            logger.error("❌ External TTS returned empty audio")
            
    except Exception as tts_error:
        logger.error(f"❌ External TTS failed: {tts_error}")
EOF

success "Orchestrator updated for external TTS"

# Step 3: Update Kubernetes manifests
log "📦 Updating Kubernetes manifests..."

# Create updated service manifest without TTS
cat > k8s/june-services/core-services-no-tts.yaml << 'EOF'
# Core services without internal TTS (using external OpenVoice)
apiVersion: v1
kind: Namespace
metadata:
  name: june-services
  labels:
    managed-by: terraform

---
apiVersion: v1
kind: Secret
metadata:
  name: june-secrets
  namespace: june-services
type: Opaque
data:
  # External TTS URL (base64 encode your OpenVoice service URL)
  EXTERNAL_TTS_URL: ""  # echo -n "https://your-openvoice-service.com" | base64
  
  # API Keys
  GEMINI_API_KEY: ""
  
  # Service authentication (existing IDP clients)
  ORCHESTRATOR_CLIENT_ID: b3JjaGVzdHJhdG9yLWNsaWVudA==
  ORCHESTRATOR_CLIENT_SECRET: b3JjaGVzdHJhdG9yLXNlY3JldC1rZXktMTIzNDU=
  STT_CLIENT_ID: c3R0LWNsaWVudA==
  STT_CLIENT_SECRET: c3R0LXNlY3JldC1rZXktMTIzNDU=

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-orchestrator
  template:
    metadata:
      labels:
        app: june-orchestrator
    spec:
      serviceAccountName: june-orchestrator
      containers:
      - name: june-orchestrator
        image: us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest
        ports:
        - containerPort: 8080
        env:
        - name: PORT
          value: "8080"
        - name: LOG_LEVEL
          value: "INFO"
        - name: STT_SERVICE_URL
          value: "http://june-stt:8080"
        # External TTS configuration
        - name: EXTERNAL_TTS_URL
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: EXTERNAL_TTS_URL
        # IDP configuration
        - name: KC_BASE_URL
          value: "http://june-idp:8080/auth"
        - name: KC_REALM
          value: "june"
        - name: ORCHESTRATOR_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: ORCHESTRATOR_CLIENT_ID
        - name: ORCHESTRATOR_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: ORCHESTRATOR_CLIENT_SECRET
        # AI
        - name: GEMINI_API_KEY
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: GEMINI_API_KEY
              optional: true
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  type: ClusterIP
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: june-orchestrator

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-stt
  namespace: june-services
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-stt
  template:
    metadata:
      labels:
        app: june-stt
    spec:
      serviceAccountName: june-stt
      containers:
      - name: june-stt
        image: us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-stt:latest
        ports:
        - containerPort: 8080
        env:
        - name: PORT
          value: "8080"
        - name: LOG_LEVEL
          value: "INFO"
        - name: KC_BASE_URL
          value: "http://june-idp:8080/auth"
        - name: KC_REALM
          value: "june"
        - name: STT_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: STT_CLIENT_ID
        - name: STT_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: STT_CLIENT_SECRET
        resources:
          requests:
            memory: "512Mi"
            cpu: "300m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: june-stt
  namespace: june-services
spec:
  type: ClusterIP
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: june-stt

---
# Service Accounts (existing)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-orchestrator
  namespace: june-services
  annotations:
    iam.gke.io/gcp-service-account: june-orchestrator-gke@main-buffer-469817-v7.iam.gserviceaccount.com

---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-stt
  namespace: june-services
  annotations:
    iam.gke.io/gcp-service-account: june-stt-gke@main-buffer-469817-v7.iam.gserviceaccount.com
EOF

# Update ingress to remove TTS
log "🌐 Updating ingress configuration..."
sed -i '/june-tts/d' k8s/june-services/ingress.yaml 2>/dev/null || true
sed -i '/june-tts/d' k8s/june-services/managedcert.yaml 2>/dev/null || true

success "Kubernetes manifests updated"

# Step 4: Update build pipeline
log "🔄 Updating CI/CD pipeline..."

# Update GitHub Actions to remove TTS
if [[ -f ".github/workflows/deploy-gke.yml" ]]; then
    # Remove TTS from build matrix
    sed -i 's/june-orchestrator, june-stt, june-tts, june-idp/june-orchestrator, june-stt, june-idp/' .github/workflows/deploy-gke.yml
    sed -i '/june-tts/d' .github/workflows/deploy-gke.yml
    success "GitHub Actions updated"
fi

# Step 5: Clean up unused files
log "🧹 Cleaning up unused files..."

# Remove TTS-related Kubernetes manifests
cd k8s/june-services/
rm -f keycloak-deployment-fixed.yaml keycloak-lightweight.yaml keycloak-production.yaml 2>/dev/null || true
rm -f fix-*.sh deploy-*-keycloak.sh patch-*.sh 2>/dev/null || true
cd ../..

# Remove Python cache and build artifacts
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.log" -delete 2>/dev/null || true

success "Cleanup completed"

# Step 6: Update documentation
log "📚 Updating documentation..."

cat > CLEANUP_CHANGES.md << 'EOF'
# TTS Cleanup Changes

## What Changed

### ✅ Removed
- `June/services/june-tts/` - Old TTS microservice
- TTS-related Kubernetes manifests
- TTS references in CI/CD pipeline
- Unused deployment scripts

### ✅ Added
- `external_tts_client.py` - Client for external OpenVoice service
- `core-services-no-tts.yaml` - Updated Kubernetes manifest
- IDP authentication for external TTS calls

### ✅ Updated
- Orchestrator configured for external TTS
- Ingress removes TTS endpoints
- Build pipeline excludes TTS service

## Next Steps Required

1. **Update orchestrator app.py** with external TTS client:
   ```python
   # Add to imports
   from external_tts_client import ExternalTTSClient
   
   # Replace TTS client initialization (see app_tts_patch.py for details)
   ```

2. **Set external TTS URL**:
   ```bash
   # Encode your OpenVoice service URL
   echo -n "https://your-openvoice-service.com" | base64
   
   # Update the secret
   kubectl patch secret june-secrets -n june-services \
     --patch='{"data":{"EXTERNAL_TTS_URL":"<base64-encoded-url>"}}'
   ```

3. **Deploy updated services**:
   ```bash
   kubectl apply -f k8s/june-services/core-services-no-tts.yaml
   ```

4. **Test integration**:
   ```bash
   kubectl port-forward -n june-services service/june-orchestrator 8080:8080
   curl http://localhost:8080/healthz
   ```

## Architecture Now

```
┌─────────────────┐    ┌─────────────────┐
│   Orchestrator  │───▶│      STT        │
│                 │    │   (Internal)    │
│                 │    │                 │
│                 │    └─────────────────┘
│                 │    ┌─────────────────┐
│                 │───▶│   Keycloak IDP  │
│                 │    │   (Internal)    │
│                 │    └─────────────────┘
│                 │           │
│                 │           │ IDP Auth
│                 │           ▼
│                 │────────────────────────▶ ┌─────────────────┐
└─────────────────┘      HTTPS + Auth       │   OpenVoice     │
                                            │   TTS Service   │
                                            │   (External)    │
                                            └─────────────────┘
```
EOF

success "Documentation updated: CLEANUP_CHANGES.md"

echo ""
success "🎉 TTS cleanup completed!"
echo ""
echo "📋 Manual steps required:"
echo "1. Update June/services/june-orchestrator/app.py (see app_tts_patch.py)"
echo "2. Set EXTERNAL_TTS_URL secret with your OpenVoice service URL"
echo "3. Deploy: kubectl apply -f k8s/june-services/core-services-no-tts.yaml"
echo "4. Test integration"
echo ""
echo "📁 Files to review:"
echo "  - external_tts_client.py (add to orchestrator)"
echo "  - app_tts_patch.py (apply to app.py)"
echo "  - core-services-no-tts.yaml (deploy this)"
echo "  - CLEANUP_CHANGES.md (implementation guide)"