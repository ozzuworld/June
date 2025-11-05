#!/usr/bin/env bash
set -euo pipefail

echo "================================================================"
echo "June Services - Docker Compose Deployment on Vast.ai"
echo "================================================================"

# Check if running on vast.ai
if [ -d "/workspace" ]; then
    echo "✅ Vast.ai environment detected"
    WORKSPACE="/workspace"
else
    echo "⚠️  Not on vast.ai, using current directory"
    WORKSPACE="$(pwd)"
fi

cd "$WORKSPACE"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found"
    echo "Please create .env from .env.example:"
    echo "  cp .env.example .env"
    echo "  nano .env  # Edit with your configuration"
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

echo ""
echo "Configuration loaded:"
echo "  ORCHESTRATOR_URL: $ORCHESTRATOR_URL"
echo "  LIVEKIT_WS_URL: $LIVEKIT_WS_URL"
echo ""

# Check for docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found, installing..."
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.23.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ docker-compose installed"
fi

# Check GPU availability
echo ""
echo "Checking GPU availability..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo "✅ GPU detected"
else
    echo "⚠️  Warning: nvidia-smi not available"
fi

# Pull latest images
echo ""
echo "================================================================"
echo "Pulling latest Docker images..."
echo "================================================================"
docker-compose pull

# Stop any existing containers
echo ""
echo "Stopping existing containers..."
docker-compose down || true

# Start services
echo ""
echo "================================================================"
echo "Starting June services..."
echo "================================================================"
docker-compose up -d

# Wait for services to be healthy
echo ""
echo "Waiting for services to become healthy..."
sleep 10

# Check service status
echo ""
echo "================================================================"
echo "Service Status:"
echo "================================================================"
docker-compose ps

# Show logs
echo ""
echo "================================================================"
echo "Service Logs (last 20 lines):"
echo "================================================================"
echo ""
echo "--- STT Logs ---"
docker-compose logs --tail=20 june-stt
echo ""
echo "--- TTS Logs ---"
docker-compose logs --tail=20 june-tts

# Health check
echo ""
echo "================================================================"
echo "Health Check:"
echo "================================================================"
sleep 5

STT_HEALTH=$(curl -sf http://localhost:8001/healthz || echo "FAILED")
TTS_HEALTH=$(curl -sf http://localhost:8000/health || echo "FAILED")

if [[ "$STT_HEALTH" == *"healthy"* ]]; then
    echo "✅ STT Service: HEALTHY"
else
    echo "❌ STT Service: UNHEALTHY"
fi

if [[ "$TTS_HEALTH" == *"healthy"* ]]; then
    echo "✅ TTS Service: HEALTHY"
else
    echo "❌ TTS Service: UNHEALTHY"
fi

echo ""
echo "================================================================"
echo "Deployment Complete!"
echo "================================================================"
echo "STT Service: http://localhost:8001"
echo "TTS Service: http://localhost:8000"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f june-stt"
echo "  docker-compose logs -f june-tts"
echo ""
echo "To check status:"
echo "  docker-compose ps"
echo ""
echo "To stop services:"
echo "  docker-compose down"
echo "================================================================"