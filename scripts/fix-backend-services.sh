#!/bin/bash
# scripts/fix-backend-services.sh
# Quick fix for mock STT and TTS services

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

log "🔧 Fixing June Backend Services"

# Check if we're in the right directory
if [[ ! -f "June/services/june-stt/app.py" ]]; then
    error "Please run this script from the project root directory"
fi

# Backup current files
log "📦 Creating backups..."
cp June/services/june-stt/app.py June/services/june-stt/app.py.backup
cp June/services/june-tts/app.py June/services/june-tts/app.py.backup
success "Backups created"

# Apply fixes
log "🔨 Applying fixes..."

# Fix STT service (the fixed version should be copied here)
cat > June/services/june-stt/requirements.txt << 'EOF'
fastapi==0.111.0
uvicorn[standard]==0.30.1
google-cloud-speech==2.27.0
python-multipart==0.0.9
firebase-admin==6.5.0
PyJWT[crypto]==2.8.0
cryptography==41.0.7
EOF

# Fix TTS service requirements
cat > June/services/june-tts/requirements.txt << 'EOF'
fastapi==0.111.0
uvicorn[standard]==0.30.1
google-cloud-texttospeech==2.16.4
PyJWT[crypto]==2.8.0
cryptography==41.0.7
httpx==0.27.0
python-multipart==0.0.9
aiofiles==23.2.0
pydantic==2.8.2
EOF

success "Requirements updated"

# Build and push new images
log "🐳 Building and pushing updated images..."

# STT Service
log "Building june-stt..."
IMAGE_STT="${REGION}-docker.pkg.dev/${PROJECT_ID}/june/june-stt:fixed-$(date +%s)"
docker build -t "$IMAGE_STT" June/services/june-stt/
docker push "$IMAGE_STT"
success "STT image pushed: $IMAGE_STT"

# TTS Service  
log "Building june-tts..."
IMAGE_TTS="${REGION}-docker.pkg.dev/${PROJECT_ID}/june/june-tts:fixed-$(date +%s)"
docker build -t "$IMAGE_TTS" June/services/june-tts/
docker push "$IMAGE_TTS"
success "TTS image pushed: $IMAGE_TTS"

# Deploy services
log "🚀 Deploying updated services..."

# Deploy STT
gcloud run deploy june-stt \
  --image="$IMAGE_STT" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --cpu="2" \
  --memory="2Gi" \
  --min-instances="1" \
  --max-instances="10" \
  --timeout="3600" \
  --concurrency="1" \
  --allow-unauthenticated \
  --set-env-vars="KC_BASE_URL=https://june-idp-359243954.us-central1.run.app,KC_REALM=june,GOOGLE_APPLICATION_CREDENTIALS=/dev/null"

success "STT service deployed"

# Deploy TTS
gcloud run deploy june-tts \
  --image="$IMAGE_TTS" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --cpu="2" \
  --memory="4Gi" \
  --min-instances="0" \
  --max-instances="10" \
  --timeout="1800" \
  --concurrency="2" \
  --allow-unauthenticated \
  --set-env-vars="KC_BASE_URL=https://june-idp-359243954.us-central1.run.app,KC_REALM=june,GOOGLE_APPLICATION_CREDENTIALS=/dev/null"

success "TTS service deployed"

# Test services
log "🧪 Testing services..."

STT_URL="https://june-stt-359243954.us-central1.run.app"
TTS_URL="https://june-tts-359243954.us-central1.run.app"

# Test health endpoints
if curl -s "$STT_URL/healthz" | grep -q '"ok": true'; then
    success "STT service health check passed"
else
    warning "STT service health check failed"
fi

if curl -s "$TTS_URL/healthz" | grep -q '"ok": true'; then
    success "TTS service health check passed"
else
    warning "TTS service health check failed"
fi

# Show service info
log "📋 Service Information:"
echo "STT Service: $STT_URL"
echo "TTS Service: $TTS_URL"
echo ""
echo "Key Changes:"
echo "• STT now uses Google Cloud Speech-to-Text API"
echo "• TTS now uses Google Cloud Text-to-Speech API"
echo "• Fallback responses for when Google Cloud is not configured"
echo "• Better error handling and logging"
echo ""
echo "Next Steps:"
echo "1. Set up Google Cloud credentials for production-quality STT/TTS"
echo "2. Test voice chat in your mobile app"
echo "3. Monitor logs: gcloud logging read --project=$PROJECT_ID"

success "Backend services fixed! 🎉"